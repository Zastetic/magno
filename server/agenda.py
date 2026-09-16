"""Motor de disponibilidade do Barbearia Magno (F3) — o coração da agenda.

A grade de dias e horários NÃO vive no HTML: ela é calculada aqui, a cada consulta, a partir
das regras da tabela `configuracoes` (`slot_min`, `buffer_min`, `antecedencia_min_h`,
`janela_dias`, `fuso`), do funcionamento (`horarios` + `excecoes`), dos `bloqueios` e dos
agendamentos já marcados. Consequência prática: assim que alguém marca um horário, ele sai
da grade de todo mundo na próxima consulta.

O `POST /api/bookings` valida pelo MESMO motor que desenha a grade (`conferir`), então o que
o site mostra é exatamente o que o servidor aceita — nada de oferta de horário que a API
recusa depois.

Convenções do banco (docs/01-MODELO-DE-DADOS.md): tudo em UTC ISO-8601 com `Z`; a grade é
pensada na hora local do fuso da loja e convertida só na borda. `fim` já inclui o
`buffer_min` (o cliente vê 10:00–10:30, a agenda reserva 10:00–10:35).
"""
from __future__ import annotations

import secrets
import sqlite3
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from server import db

# Status que ocupam a cadeira: `concluido` também ocupa, senão um agendamento antigo poderia
# ser sobrescrito e o histórico reescrito (mesma regra da query de ocupação dos docs).
STATUS_OCUPAM = ("agendado", "confirmado", "concluido")

# Por que não há slot nenhum — o front usa isso para explicar em vez de mostrar tela vazia.
LOJA_FECHADA = "loja_fechada"
FORA_DA_JANELA = "fora_da_janela"
SEM_PROFISSIONAL = "sem_profissional_habilitado"
ANTECEDENCIA = "antecedencia_minima"
SEM_ESPACO = "sem_espaco_no_dia"
DIA_LOTADO = "dia_lotado"
# Motivos de recusa do `POST` (não aparecem na consulta pública).
PASSOU = "horario_passado"
FORA_DA_GRADE = "fora_da_grade"
OCUPADO = "ocupado"
CLIENTE_OCUPADO = "cliente_ocupado"

MOTIVOS_TEXTO = {
    LOJA_FECHADA: "A loja está fechada nesse dia.",
    FORA_DA_JANELA: "Esse dia está fora do período de agendamento.",
    SEM_PROFISSIONAL: "Nenhum barbeiro da casa faz esse serviço.",
    ANTECEDENCIA: "Não dá mais tempo hoje: a loja pede {horas} h de antecedência.",
    SEM_ESPACO: "Esse serviço não cabe no horário de funcionamento desse dia.",
    DIA_LOTADO: "Sem vaga nesse dia — tente outro.",
}

# Motivo de recusa → (HTTP, código do erro, mensagem). `{horas}` sai de antecedencia_min_h.
RECUSAS: dict[str, tuple[int, str, str]] = {
    OCUPADO: (409, "horario_ocupado", "Esse horário acabou de ser ocupado. Escolha outro."),
    CLIENTE_OCUPADO: (409, "ja_tem_agendamento", "Você já tem um agendamento nesse horário."),
    PASSOU: (400, "horario_passado", "Escolha um horário futuro."),
    ANTECEDENCIA: (400, "horario_passado", "A loja pede pelo menos {horas} h de antecedência."),
    FORA_DA_JANELA: (400, "horario_invalido", "Esse dia está fora do período de agendamento."),
    LOJA_FECHADA: (400, "horario_invalido", "A loja está fechada nesse dia."),
    FORA_DA_GRADE: (400, "horario_invalido", "Esse horário não faz parte da grade do dia."),
    SEM_PROFISSIONAL: (404, "indisponivel", "Esse barbeiro não faz esse serviço."),
}

JANELA_MAX_DIAS = 31  # teto do `de`/`ate` numa consulta só (o docs/02-API.md promete 31)


class HorarioOcupado(Exception):
    """Conflito na hora de gravar: vira 409 na API, com o código certo."""

    def __init__(self, mensagem: str, codigo: str = "horario_ocupado"):
        super().__init__(mensagem)
        self.codigo = codigo


# ------------------------------------------------------------------- regras
def _inteiro(chave: str, padrao: int) -> int:
    try:
        return int(str(db.config(chave)))
    except (TypeError, ValueError):
        return padrao


def regras() -> dict:
    """Regras de negócio do motor — todas de `configuracoes`, nenhuma constante no código."""
    return {
        "slot_min": max(5, _inteiro("slot_min", 30)),
        "buffer_min": max(0, _inteiro("buffer_min", 5)),
        "antecedencia_min_h": max(0, _inteiro("antecedencia_min_h", 1)),
        "janela_dias": max(1, _inteiro("janela_dias", 60)),
        "fuso": (db.config("fuso") or "America/Sao_Paulo").strip() or "America/Sao_Paulo",
    }


def fuso(nome: str | None = None) -> ZoneInfo:
    try:
        return ZoneInfo(nome or regras()["fuso"])
    except Exception:  # fuso inválido na configuração nunca derruba a agenda
        return ZoneInfo("America/Sao_Paulo")


def dia_semana(dia: date) -> int:
    """Python conta 0=segunda; o banco conta 0=domingo (`horarios.dia_semana`)."""
    return (dia.weekday() + 1) % 7


def _hora(texto: str) -> time:
    partes = str(texto).split(":")
    return time(int(partes[0]), int(partes[1]))


def _utc(texto) -> datetime:
    return datetime.strptime(str(texto), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _iso(momento: datetime) -> str:
    return momento.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def texto_motivo(motivo: str | None, regra: dict | None = None) -> str | None:
    if not motivo:
        return None
    texto = MOTIVOS_TEXTO.get(motivo)
    if texto is None:
        return None
    return texto.format(horas=(regra or regras())["antecedencia_min_h"])


def recusa(motivo: str, regra: dict | None = None) -> tuple[int, str, str]:
    """(HTTP, código, mensagem) para uma recusa de agendamento."""
    http, codigo, mensagem = RECUSAS.get(motivo, (400, "horario_invalido", "Horário indisponível."))
    return http, codigo, mensagem.format(horas=(regra or regras())["antecedencia_min_h"])


# ------------------------------------------------------------- funcionamento
def funcionamento(con: sqlite3.Connection, dia: date) -> dict | None:
    """(abre, fecha) do dia em hora local, ou None se a loja está fechada.

    A exceção da data vence o horário semanal (feriado fechado ou horário especial).
    """
    excecao = con.execute(
        "SELECT fechado, abre, fecha, motivo FROM excecoes WHERE data = ?", (dia.isoformat(),)
    ).fetchone()
    if excecao:
        if excecao["fechado"]:
            return None
        if excecao["abre"] and excecao["fecha"]:
            return {"abre": _hora(excecao["abre"]), "fecha": _hora(excecao["fecha"]),
                    "motivo": excecao["motivo"]}
    semanal = con.execute(
        "SELECT abre, fecha, ativo FROM horarios WHERE dia_semana = ?", (dia_semana(dia),)
    ).fetchone()
    if not semanal or not semanal["ativo"]:
        return None
    return {"abre": _hora(semanal["abre"]), "fecha": _hora(semanal["fecha"]), "motivo": None}


# ----------------------------------------------------------------- ocupação
def ocupacao(con: sqlite3.Connection, profissional_id: int, de_utc: datetime,
             ate_utc: datetime) -> list[tuple[datetime, datetime]]:
    """Agendamentos ativos + bloqueios do profissional que tocam o intervalo — uma query só."""
    linhas = con.execute(
        """SELECT inicio, fim FROM agendamentos
            WHERE profissional_id = ? AND status IN ('agendado','confirmado','concluido')
              AND inicio < ? AND fim > ?
           UNION ALL
           SELECT inicio, fim FROM bloqueios
            WHERE profissional_id = ? AND inicio < ? AND fim > ?""",
        (profissional_id, _iso(ate_utc), _iso(de_utc),
         profissional_id, _iso(ate_utc), _iso(de_utc)),
    ).fetchall()
    return [(_utc(linha["inicio"]), _utc(linha["fim"])) for linha in linhas]


def _ocupacao_do_cliente(con: sqlite3.Connection, cliente_id: int, de_utc: datetime,
                         ate_utc: datetime) -> list[tuple[datetime, datetime]]:
    """Agendamentos ativos do próprio cliente (regra 7: ninguém marca dois no mesmo horário)."""
    linhas = con.execute(
        """SELECT inicio, fim FROM agendamentos
            WHERE cliente_id = ? AND status IN ('agendado','confirmado')
              AND inicio < ? AND fim > ?""",
        (cliente_id, _iso(ate_utc), _iso(de_utc)),
    ).fetchall()
    return [(_utc(linha["inicio"]), _utc(linha["fim"])) for linha in linhas]


def _sobrepoe(intervalos: list[tuple[datetime, datetime]], inicio: datetime, fim: datetime) -> bool:
    return any(comeco < fim and termino > inicio for comeco, termino in intervalos)


def profissionais_habilitados(con: sqlite3.Connection, servico_id: int,
                              profissional_id: int | None = None) -> list[dict]:
    """Barbeiros ativos que executam o serviço (`servico_profissional` filtra quem faz o quê)."""
    sql = """SELECT p.id, p.apelido, p.bio, u.nome
               FROM profissionais p
               JOIN usuarios u ON u.id = p.usuario_id
               JOIN servico_profissional sp ON sp.profissional_id = p.id
              WHERE sp.servico_id = ? AND p.ativo = 1 AND u.ativo = 1"""
    parametros: list = [servico_id]
    if profissional_id is not None:
        sql += " AND p.id = ?"
        parametros.append(profissional_id)
    sql += " ORDER BY p.ordem, u.nome"
    return [dict(linha) for linha in con.execute(sql, parametros)]


# -------------------------------------------------------------------- grade
def slots_do_dia(con: sqlite3.Connection, servico: dict, profissional_id: int, dia: date, *,
                 momento: datetime | None = None, regra: dict | None = None) -> dict:
    """Slots livres do profissional num dia, em datetime local, + o motivo se não houver nenhum.

    A grade anda de `slot_min` em `slot_min` a partir da abertura; um slot só entra se o
    serviço termina dentro do horário de funcionamento (slot parcial no fim do dia é
    descartado) e se o intervalo [início, início + duração + buffer) não encosta em nenhum
    agendamento ativo nem bloqueio (`START IMMEDIATE` não: aqui é só leitura).
    """
    regra = regra or regras()
    zona = fuso(regra["fuso"])
    momento = momento or datetime.now(zona)
    duracao = int(servico["duracao_min"])
    passo = timedelta(minutes=regra["slot_min"])
    ocupado_por = timedelta(minutes=duracao + regra["buffer_min"])

    if dia < momento.date() or dia > momento.date() + timedelta(days=regra["janela_dias"]):
        return {"slots": [], "motivo": FORA_DA_JANELA, "na_grade": 0}

    faixa = funcionamento(con, dia)
    if not faixa:
        return {"slots": [], "motivo": LOJA_FECHADA, "na_grade": 0}

    meia_noite = datetime.combine(dia, time(0, 0), tzinfo=zona)
    ocupados = ocupacao(con, profissional_id, meia_noite, meia_noite + timedelta(days=1))

    minimo = momento + timedelta(hours=regra["antecedencia_min_h"])
    atual = datetime.combine(dia, faixa["abre"], tzinfo=zona)
    limite = datetime.combine(dia, faixa["fecha"], tzinfo=zona)
    livres: list[datetime] = []
    na_grade = cedo = 0
    while atual + timedelta(minutes=duracao) <= limite:
        na_grade += 1
        if atual < minimo:
            cedo += 1
        elif not _sobrepoe(ocupados, atual.astimezone(timezone.utc),
                           (atual + ocupado_por).astimezone(timezone.utc)):
            livres.append(atual)
        atual += passo

    motivo = None
    if not livres:
        if not na_grade:
            motivo = SEM_ESPACO          # o serviço não cabe no dia (ex: 90 min num sábado curto)
        elif cedo == na_grade:
            motivo = ANTECEDENCIA        # o dia inteiro já passou do prazo de antecedência
        else:
            motivo = DIA_LOTADO
    return {"slots": livres, "motivo": motivo, "na_grade": na_grade}


def conferir(con: sqlite3.Connection, servico: dict, profissional_id: int, inicio_local: datetime,
             *, cliente_id: int | None = None, momento: datetime | None = None,
             regra: dict | None = None) -> tuple[bool, str | None]:
    """O horário pedido está na grade e livre? Devolve (ok, motivo).

    É o mesmo critério da grade mostrada ao cliente — a API não aceita nada que o site não
    ofereça, e não oferece nada que a API recusaria.
    """
    regra = regra or regras()
    zona = fuso(regra["fuso"])
    momento = momento or datetime.now(zona)
    if inicio_local.tzinfo is None:
        inicio_local = inicio_local.replace(tzinfo=zona)
    dia = inicio_local.date()
    duracao = int(servico["duracao_min"])

    if dia < momento.date():
        return False, PASSOU
    if dia > momento.date() + timedelta(days=regra["janela_dias"]):
        return False, FORA_DA_JANELA
    if inicio_local <= momento:
        return False, PASSOU
    if inicio_local < momento + timedelta(hours=regra["antecedencia_min_h"]):
        return False, ANTECEDENCIA

    faixa = funcionamento(con, dia)
    if not faixa:
        return False, LOJA_FECHADA
    abre = datetime.combine(dia, faixa["abre"], tzinfo=zona)
    fecha = datetime.combine(dia, faixa["fecha"], tzinfo=zona)
    minutos_desde_abertura = int(
        (inicio_local.replace(tzinfo=None) - abre.replace(tzinfo=None)).total_seconds() // 60)
    if minutos_desde_abertura < 0 or minutos_desde_abertura % regra["slot_min"]:
        return False, FORA_DA_GRADE
    if inicio_local + timedelta(minutes=duracao) > fecha:
        return False, FORA_DA_GRADE

    habilitado = con.execute(
        "SELECT 1 FROM servico_profissional WHERE servico_id = ? AND profissional_id = ?",
        (servico["id"], profissional_id),
    ).fetchone()
    if not habilitado:
        return False, SEM_PROFISSIONAL
    ativo = con.execute(
        "SELECT 1 FROM profissionais p JOIN usuarios u ON u.id = p.usuario_id "
        "WHERE p.id = ? AND p.ativo = 1 AND u.ativo = 1", (profissional_id,)
    ).fetchone()
    if not ativo:
        return False, SEM_PROFISSIONAL

    inicio_utc = inicio_local.astimezone(timezone.utc)
    fim_utc = (inicio_local + timedelta(minutes=duracao + regra["buffer_min"])).astimezone(timezone.utc)
    folga = timedelta(days=2)
    if _sobrepoe(ocupacao(con, profissional_id, inicio_utc - folga, fim_utc + folga), inicio_utc, fim_utc):
        return False, OCUPADO
    if cliente_id:
        do_cliente = _ocupacao_do_cliente(con, cliente_id, inicio_utc - folga, fim_utc + folga)
        # aqui só a duração conta: o buffer é do profissional, não impede o cliente de emendar
        if _sobrepoe(do_cliente, inicio_utc,
                     (inicio_local + timedelta(minutes=duracao)).astimezone(timezone.utc)):
            return False, CLIENTE_OCUPADO
    return True, None


def marcar(cliente_id: int, servico: dict, profissional_id: int, inicio_local: datetime, *,
           regra: dict | None = None, momento: datetime | None = None) -> dict:
    """Grava o agendamento em `BEGIN IMMEDIATE`: checagem de conflito e INSERT na mesma transação.

    Duas requisições simultâneas no mesmo slot: a transação de escrita serializa (busy_timeout
    de 5 s) e a segunda vê a linha já gravada → 409. O índice único parcial
    (`idx_ag_slot_unico`) é a segunda linha de defesa, para o caso de escapar alguma.
    O `rollback` nos `except` é obrigatório: sem ele a conexão segura o lock e todo mundo
    recebe `database is locked` (pitfall já pago, ver docs/01-MODELO-DE-DADOS.md).
    """
    regra = regra or regras()
    zona = fuso(regra["fuso"])
    if inicio_local.tzinfo is None:
        inicio_local = inicio_local.replace(tzinfo=zona)
    duracao = int(servico["duracao_min"])
    inicio_utc = inicio_local.astimezone(timezone.utc)
    fim_utc = (inicio_local + timedelta(minutes=duracao + regra["buffer_min"])).astimezone(timezone.utc)

    con = db.conectar()
    try:
        con.execute("BEGIN IMMEDIATE")
        ok, motivo = conferir(con, servico, profissional_id, inicio_local, cliente_id=cliente_id,
                              momento=momento, regra=regra)
        if not ok:
            con.rollback()
            _, codigo, mensagem = recusa(motivo or OCUPADO, regra)
            raise HorarioOcupado(mensagem, codigo)
        cursor = con.execute(
            """INSERT INTO agendamentos (codigo, cliente_id, profissional_id, servico_id, inicio, fim,
                                         duracao_min, preco_centavos, origem)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'cliente')""",
            (secrets.token_urlsafe(8), cliente_id, profissional_id, int(servico["id"]),
             _iso(inicio_utc), _iso(fim_utc), duracao, int(servico["preco_centavos"])),
        )
        con.commit()
        return dict(con.execute("SELECT * FROM agendamentos WHERE id = ?", (cursor.lastrowid,)).fetchone())
    except sqlite3.IntegrityError:
        con.rollback()
        raise HorarioOcupado("Esse horário acabou de ser ocupado. Escolha outro.")
    finally:
        con.close()


def disponivel(con: sqlite3.Connection, servico: dict, profissional_id: int | None, dia: date, *,
               momento: datetime | None = None, regra: dict | None = None) -> dict:
    """Grade de um dia, agregando os profissionais habilitados (quando nenhum é escolhido)."""
    regra = regra or regras()
    momento = momento or datetime.now(fuso(regra["fuso"]))
    barbeiros = profissionais_habilitados(con, int(servico["id"]), profissional_id)
    por_profissional, vazio = [], None
    if not barbeiros:
        vazio = SEM_PROFISSIONAL
    for barbeiro in barbeiros:
        resultado = slots_do_dia(con, servico, barbeiro["id"], dia, momento=momento, regra=regra)
        por_profissional.append({
            "profissional_id": barbeiro["id"],
            "nome": barbeiro["nome"],
            "apelido": barbeiro["apelido"] or barbeiro["nome"],
            "slots": [_iso(slot.astimezone(timezone.utc)) for slot in resultado["slots"]],
            "motivo_vazio": resultado["motivo"],
        })
        if not resultado["slots"] and vazio is None:
            vazio = resultado["motivo"]
    tem_slot = any(item["slots"] for item in por_profissional)
    if tem_slot:
        vazio = None
    return {
        "servico_id": int(servico["id"]),
        "duracao_min": int(servico["duracao_min"]),
        "fuso": regra["fuso"],
        "data": dia.isoformat(),
        "profissionais": por_profissional,
        "motivo_vazio": vazio,
        "motivo_texto": texto_motivo(vazio, regra),
    }


def resumo_dias(con: sqlite3.Connection, servico: dict, de: date, ate: date,
                profissional_id: int | None = None, *, momento: datetime | None = None,
                regra: dict | None = None) -> dict:
    """Contagem de vagas por dia (para a tira de dias do site) — uma passada, sem N+1 de rede."""
    regra = regra or regras()
    momento = momento or datetime.now(fuso(regra["fuso"]))
    barbeiros = profissionais_habilitados(con, int(servico["id"]), profissional_id)
    dias = []
    total_dias = (ate - de).days + 1
    for indice in range(total_dias):
        dia = de + timedelta(days=indice)
        livres, primeiro, vazio = 0, None, None
        for barbeiro in barbeiros:
            resultado = slots_do_dia(con, servico, barbeiro["id"], dia, momento=momento, regra=regra)
            livres += len(resultado["slots"])
            if resultado["slots"]:
                candidato = min(resultado["slots"])
                if primeiro is None or candidato < primeiro:
                    primeiro = candidato
            if not resultado["slots"] and vazio is None:
                vazio = resultado["motivo"]
        if not barbeiros:
            vazio = SEM_PROFISSIONAL
        if livres:
            vazio = None
        dias.append({
            "data": dia.isoformat(),
            "livres": livres,
            "primeiro": _iso(primeiro.astimezone(timezone.utc)) if primeiro else None,
            "motivo_vazio": vazio,
            "motivo_texto": texto_motivo(vazio, regra),
        })
    return {
        "servico_id": int(servico["id"]),
        "duracao_min": int(servico["duracao_min"]),
        "fuso": regra["fuso"],
        "de": de.isoformat(),
        "ate": ate.isoformat(),
        "dias": dias,
    }
