"""Motor de disponibilidade (F3): a grade que o site mostra é a mesma que a API aceita.

Cada teste cria o próprio barbeiro (a base de teste nasce sem nenhum) e usa datas futuras
calculadas na hora, para não depender do dia em que a suíte roda. As datas fixas (2027)
servem para checar grade pura, sem relação com "hoje".
"""
from __future__ import annotations

import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from itertools import count

import pytest
from fastapi.testclient import TestClient

from server import agenda, db
from server.main import app

FUSO = agenda.fuso()
PIN = "9471"
_novos = count(81001)


@pytest.fixture
def cliente():
    with TestClient(app) as c:
        yield c


@contextmanager
def conexao():
    con = db.conectar()
    try:
        yield con
    finally:
        con.close()


def momento(dia: str, hora: str) -> datetime:
    return datetime.strptime(f"{dia} {hora}", "%Y-%m-%d %H:%M").replace(tzinfo=FUSO)


def quando(iso: str) -> datetime:
    return datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).astimezone(FUSO)


def servico(nome: str = "Corte masculino") -> dict:
    return dict(db.obter_servico_por_nome(nome))


def barbeiro(servicos: list[str] | None = None) -> dict:
    """Profissional novo, habilitado nos serviços pedidos (todos, por padrão)."""
    apelido = f"Barbeiro{next(_novos)}"
    nomes = servicos or ["Corte masculino", "Barba", "Corte + barba", "Degradê navalhado"]
    with conexao() as con:
        usuario_id = con.execute(
            "INSERT INTO usuarios (nome, email, papel) VALUES (?, ?, 'barbeiro')",
            (apelido, f"{apelido.lower()}@exemplo.test")).lastrowid
        profissional_id = con.execute(
            "INSERT INTO profissionais (usuario_id, apelido) VALUES (?, ?)",
            (usuario_id, apelido)).lastrowid
        for nome in nomes:
            linha = con.execute("SELECT id FROM servicos WHERE nome = ?", (nome,)).fetchone()
            con.execute("INSERT INTO servico_profissional (servico_id, profissional_id) VALUES (?, ?)",
                        (linha["id"], profissional_id))
        con.commit()
        return dict(con.execute(
            """SELECT p.*, u.nome FROM profissionais p JOIN usuarios u ON u.id = p.usuario_id
                WHERE p.id = ?""", (profissional_id,)).fetchone())


def slots(profissional_id: int, dia: str, *, carga: datetime | None = None, hora: str = "07:00",
          servico_nome: str = "Corte masculino", regra: dict | None = None) -> dict:
    with conexao() as con:
        return agenda.slots_do_dia(con, servico(servico_nome), profissional_id,
                                   datetime.strptime(dia, "%Y-%m-%d").date(),
                                   momento=carga or momento(dia, hora), regra=regra)


def usuario_teste(papel: str = "cliente") -> int:
    """Usuário de verdade no banco: `agendamentos.cliente_id` tem chave estrangeira."""
    with conexao() as con:
        identificador = next(_novos)
        usuario_id = con.execute(
            "INSERT INTO usuarios (nome, email, papel) VALUES (?, ?, ?)",
            (f"Cliente {identificador}", f"cliente{identificador}@exemplo.test", papel)).lastrowid
        con.commit()
        return int(usuario_id)


def cadastrar(cliente, nome="Cliente Agenda") -> dict:
    telefone = f"55139981{next(_novos):05d}"
    resposta = cliente.post("/api/auth/cadastro", json={
        "nome": nome, "telefone": telefone, "pin": PIN, "consentimento_lgpd": True})
    assert resposta.status_code == 200, resposta.text
    return resposta.json()


def primeiro_slot_livre(cliente, servico_id: int, profissional_id: int) -> tuple[str, str, str]:
    """(data, hora local, iso UTC) do primeiro horário livre nos próximos 20 dias."""
    hoje = datetime.now(FUSO).date()
    for deslocamento in range(2, 22):
        dia = (hoje + timedelta(days=deslocamento)).isoformat()
        resposta = cliente.get("/api/publica/disponibilidade"
                               f"?servico_id={servico_id}&profissional_id={profissional_id}&data={dia}")
        assert resposta.status_code == 200, resposta.text
        disponiveis = resposta.json()["profissionais"][0]["slots"]
        if disponiveis:
            local = quando(disponiveis[0])
            return dia, local.strftime("%H:%M"), disponiveis[0]
    raise AssertionError("nenhum dia com vaga nos próximos 20 dias")


# =============================================================== grade pura
def test_grade_vai_da_abertura_ao_ultimo_slot_que_cabe(cliente):
    """Segunda 15/03/2027: abre 09:00, fecha 19:00, slot 30 min → 20 vagas de 09:00 a 18:30."""
    equipe = barbeiro()
    resultado = slots(equipe["id"], "2027-03-15")
    assert resultado["motivo"] is None
    assert len(resultado["slots"]) == 20
    assert resultado["slots"][0].strftime("%H:%M") == "09:00"
    assert resultado["slots"][-1].strftime("%H:%M") == "18:30"
    # 09:00 em America/Sao_Paulo é 12:00Z (offset -03 desde 2019, sem horário de verão)
    assert agenda._iso(resultado["slots"][0].astimezone(timezone.utc)) == "2027-03-15T12:00:00Z"


def test_slot_parcial_no_fim_do_dia_fica_de_fora(cliente):
    """Sábado abre 08:00 e fecha 18:00; um serviço de 45 min não cabe às 17:30."""
    equipe = barbeiro()
    resultado = slots(equipe["id"], "2027-03-20", servico_nome="Degradê navalhado")
    horarios = [slot.strftime("%H:%M") for slot in resultado["slots"]]
    assert horarios[-1] == "17:00", horarios[-3:]
    assert "17:30" not in horarios


def test_servico_que_nao_cabe_no_dia_explica_o_motivo(cliente):
    """Horário especial de 1 h (exceção) + serviço de 2 h = nenhuma vaga possível."""
    equipe = barbeiro()
    dia = "2027-04-07"
    with conexao() as con:
        servico_id = con.execute(
            """INSERT INTO servicos (nome, duracao_min, preco_centavos, ordem)
               VALUES ('Serviço longo de teste', 120, 1000, 99)""").lastrowid
        con.execute("INSERT INTO servico_profissional (servico_id, profissional_id) VALUES (?, ?)",
                    (servico_id, equipe["id"]))
        con.execute("INSERT INTO excecoes (data, fechado, abre, fecha, motivo) VALUES (?, 0, '10:00', '11:00', 'teste')",
                    (dia,))
        con.commit()
    try:
        with conexao() as con:
            resultado = agenda.slots_do_dia(con, dict(db.obter_servico(servico_id)), equipe["id"],
                                            datetime.strptime(dia, "%Y-%m-%d").date(),
                                            momento=momento(dia, "07:00"))
        assert resultado["slots"] == []
        assert resultado["motivo"] == agenda.SEM_ESPACO
    finally:
        with conexao() as con:  # limpa para os outros testes
            con.execute("DELETE FROM excecoes WHERE data = ?", (dia,))
            con.execute("DELETE FROM servico_profissional WHERE servico_id = ?", (servico_id,))
            con.execute("DELETE FROM servicos WHERE id = ?", (servico_id,))
            con.commit()


def test_antecedencia_minima_esconde_as_primeiras_horas(cliente):
    equipe = barbeiro()
    resultado = slots(equipe["id"], "2027-03-15", hora="09:00")  # 1 h de antecedência
    horarios = [slot.strftime("%H:%M") for slot in resultado["slots"]]
    assert horarios[0] == "10:00", horarios[:3]
    assert "09:30" not in horarios


def test_dia_inteiro_dentro_da_antecedencia_tem_motivo_proprio(cliente):
    equipe = barbeiro()
    resultado = slots(equipe["id"], "2027-03-15", hora="18:30")
    assert resultado["slots"] == []
    assert resultado["motivo"] == agenda.ANTECEDENCIA


def test_domingo_a_loja_esta_fechada(cliente):
    equipe = barbeiro()
    resultado = slots(equipe["id"], "2027-03-21")  # domingo
    assert resultado["slots"] == []
    assert resultado["motivo"] == agenda.LOJA_FECHADA


@pytest.mark.parametrize("deslocamento", [-1, 61])
def test_fora_da_janela_nao_devolve_slot(cliente, deslocamento):
    """-1 é ontem; 61 (+1 do que `janela_dias` promete) ainda está fora."""
    regra = agenda.regras()
    assert deslocamento == -1 or deslocamento > regra["janela_dias"]
    equipe = barbeiro()
    dia = (datetime.now(FUSO).date() + timedelta(days=deslocamento)).isoformat()
    resultado = slots(equipe["id"], dia, carga=datetime.now(FUSO))
    assert resultado["slots"] == []
    assert resultado["motivo"] == agenda.FORA_DA_JANELA


def test_excecao_de_feriado_fecha_e_horario_especial_abre(cliente):
    equipe = barbeiro()
    feriado, especial = "2027-05-03", "2027-05-04"
    with conexao() as con:
        con.execute("INSERT INTO excecoes (data, fechado, motivo) VALUES (?, 1, 'feriado')", (feriado,))
        con.execute("INSERT INTO excecoes (data, fechado, abre, fecha, motivo) VALUES (?, 0, '10:00', '12:00', 'especial')",
                    (especial,))
        con.commit()
    try:
        fechado = slots(equipe["id"], feriado)
        assert fechado["slots"] == [] and fechado["motivo"] == agenda.LOJA_FECHADA
        aberto = slots(equipe["id"], especial)
        horarios = [slot.strftime("%H:%M") for slot in aberto["slots"]]
        assert horarios == ["10:00", "10:30", "11:00", "11:30"], horarios
    finally:
        with conexao() as con:
            con.execute("DELETE FROM excecoes WHERE data IN (?, ?)", (feriado, especial))
            con.commit()


def test_bloqueio_do_profissional_remove_slots_e_respeita_o_buffer(cliente):
    equipe = barbeiro()
    dia = "2027-06-14"  # segunda
    inicio = momento(dia, "14:00").astimezone(timezone.utc)
    fim = momento(dia, "16:00").astimezone(timezone.utc)
    with conexao() as con:
        bloqueio_id = con.execute(
            "INSERT INTO bloqueios (profissional_id, inicio, fim, motivo) VALUES (?, ?, ?, 'almoço')",
            (equipe["id"], agenda._iso(inicio), agenda._iso(fim))).lastrowid
        con.commit()
    try:
        horarios = [slot.strftime("%H:%M") for slot in slots(equipe["id"], dia)["slots"]]
        for fora in ("13:30", "14:00", "14:30", "15:00", "15:30"):
            assert fora not in horarios, fora          # 13:30 porque o buffer de 5 min encosta no bloqueio
        assert "13:00" in horarios and "16:00" in horarios
    finally:
        with conexao() as con:
            con.execute("DELETE FROM bloqueios WHERE id = ?", (bloqueio_id,))
            con.commit()


def test_fuso_configuravel_muda_o_offset_utc_do_mesmo_horario(cliente):
    """Mesmo 09:00 da parede: em Nova York o inverno é UTC-5 e o verão é UTC-4."""
    equipe = barbeiro()
    regra = dict(agenda.regras(), fuso="America/New_York")
    inverno = slots(equipe["id"], "2027-02-15", regra=regra)   # segunda
    verao = slots(equipe["id"], "2027-03-15", regra=regra)     # primeira segunda depois do DST
    assert inverno["slots"][0].strftime("%H:%M") == "09:00"
    assert verao["slots"][0].strftime("%H:%M") == "09:00"
    assert inverno["slots"][0].astimezone(timezone.utc).hour == 14
    assert verao["slots"][0].astimezone(timezone.utc).hour == 13


# ======================================================= ocupação e conflito
def test_marcar_ocupa_a_vaga_e_o_buffer_e_o_fim_ja_inclui_o_buffer(cliente):
    equipe = barbeiro()
    dia = "2027-07-05"  # segunda
    with conexao() as con:
        agendamento = agenda.marcar(usuario_teste(), servico("Corte masculino"), equipe["id"],
                                    momento(dia, "09:00"), momento=momento(dia, "08:00"))
    assert quando(agendamento["inicio"]).strftime("%H:%M") == "09:00"
    assert quando(agendamento["fim"]).strftime("%H:%M") == "09:35"   # 30 min + 5 de buffer

    horarios = [slot.strftime("%H:%M") for slot in slots(equipe["id"], dia)["slots"]]
    assert "09:00" not in horarios        # já é de alguém
    assert "09:30" not in horarios        # cai dentro do buffer
    assert "10:00" in horarios            # este continua livre


def test_cliente_nao_marca_dois_servicos_no_mesmo_horario(cliente):
    """Regra 7 do plano: o mesmo cliente não fica com dois horários sobrepostos."""
    primeiro, segundo = barbeiro(), barbeiro()
    dia = "2027-07-06"
    cliente_id = usuario_teste()
    with conexao() as con:
        agenda.marcar(cliente_id, servico("Corte masculino"), primeiro["id"], momento(dia, "09:00"),
                      momento=momento(dia, "08:00"))
        with pytest.raises(agenda.HorarioOcupado) as erro:
            agenda.marcar(cliente_id, servico("Barba"), segundo["id"], momento(dia, "09:00"),
                          momento=momento(dia, "08:00"))
    assert erro.value.codigo == "ja_tem_agendamento"
    # outro cliente no mesmo horário passa: a cadeira é do Bruno, que está livre
    with conexao() as con:
        agenda.marcar(usuario_teste(), servico("Barba"), segundo["id"], momento(dia, "09:00"),
                      momento=momento(dia, "08:00"))


def test_conferir_recusa_fora_da_grade_e_no_passado(cliente):
    equipe = barbeiro()
    dia = "2027-08-09"
    carga = momento(dia, "08:00")
    with conexao() as con:
        cortar = servico("Corte masculino")
        assert agenda.conferir(con, cortar, equipe["id"], momento(dia, "14:07"), momento=carga) == (False, agenda.FORA_DA_GRADE)
        assert agenda.conferir(con, cortar, equipe["id"], momento(dia, "19:00"), momento=carga) == (False, agenda.FORA_DA_GRADE)
        assert agenda.conferir(con, cortar, equipe["id"], momento(dia, "18:45"), momento=carga) == (False, agenda.FORA_DA_GRADE)
        assert agenda.conferir(con, cortar, equipe["id"], momento(dia, "07:30"), momento=carga) == (False, agenda.PASSOU)
        assert agenda.conferir(con, cortar, equipe["id"], momento(dia, "08:30"), momento=carga) == (False, agenda.ANTECEDENCIA)
        assert agenda.conferir(con, cortar, equipe["id"], momento(dia, "09:00"), momento=carga) == (True, None)
        # serviço que o barbeiro não executa
        outra = dict(db.obter_servico_por_nome("Barba"))
        with conexao() as interna:
            interna.execute("DELETE FROM servico_profissional WHERE profissional_id = ? AND servico_id = ?",
                            (equipe["id"], outra["id"]))
            interna.commit()
        assert agenda.conferir(con, outra, equipe["id"], momento(dia, "09:00"), momento=carga) == (False, agenda.SEM_PROFISSIONAL)


def test_dois_pedidos_no_mesmo_slot_so_um_vence(cliente):
    """A prova do overbooking: duas threads no mesmo horário → um cria, o outro recebe conflito."""
    equipe = barbeiro()
    cortar = servico("Corte masculino")
    vencedores, perdedores = 0, 0
    for indice in range(5):
        dia = f"2027-09-{6 + indice:02d}"  # segunda a sexta
        inicio = momento(dia, "15:00")
        resultados: list[str] = []
        trava = threading.Barrier(2)

        def tentar(cliente_id: int) -> None:
            trava.wait()
            try:
                agenda.marcar(cliente_id, cortar, equipe["id"], inicio, momento=momento(dia, "08:00"))
                resultados.append("criou")
            except agenda.HorarioOcupado:
                resultados.append("conflito")

        clientes = [usuario_teste(), usuario_teste()]
        threads = [threading.Thread(target=tentar, args=(clientes[n],)) for n in (0, 1)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert sorted(resultados) == ["conflito", "criou"], resultados
        vencedores += resultados.count("criou")
        perdedores += resultados.count("conflito")

    assert (vencedores, perdedores) == (5, 5)
    with conexao() as con:
        duplicados = con.execute(
            """SELECT COUNT(*) AS c FROM (
                 SELECT profissional_id, inicio FROM agendamentos
                  WHERE profissional_id = ? AND status IN ('agendado','confirmado','concluido')
                  GROUP BY profissional_id, inicio HAVING COUNT(*) > 1)""",
            (equipe["id"],)).fetchone()["c"]
    assert duplicados == 0, "dois agendamentos no mesmo horário"


# ============================================================ API pública
def test_disponibilidade_e_publica_e_traz_a_grade_do_dia(cliente):
    equipe = barbeiro()
    cortar = servico("Corte masculino")
    hoje = datetime.now(FUSO).date()
    dia = (hoje + timedelta(days=3)).isoformat()
    resposta = cliente.get("/api/publica/disponibilidade"
                           f"?servico_id={cortar['id']}&profissional_id={equipe['id']}&data={dia}")
    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert corpo["fuso"] == agenda.regras()["fuso"]
    assert corpo["duracao_min"] == 30
    barbeiro_do_dia = corpo["profissionais"][0]
    assert barbeiro_do_dia["profissional_id"] == equipe["id"]
    assert barbeiro_do_dia["nome"] == equipe["nome"]
    for slot in barbeiro_do_dia["slots"]:
        assert len(slot) == 20 and slot.endswith("Z")
        assert slot not in ("", None)


def test_agendar_pelo_site_remove_o_horario_da_grade(cliente):
    """O pedido do Okai, testado de ponta a ponta: marcar → o horário sai da grade."""
    equipe = barbeiro()
    cortar = servico("Corte masculino")
    dia, hora, iso = primeiro_slot_livre(cliente, cortar["id"], equipe["id"])
    conta = cadastrar(cliente)
    cabecalho = {"Authorization": "Bearer " + conta["token"]}

    antes = cliente.get("/api/publica/disponibilidade"
                        f"?servico_id={cortar['id']}&profissional_id={equipe['id']}&data={dia}").json()
    assert iso in antes["profissionais"][0]["slots"]

    reserva = cliente.post("/api/bookings", headers=cabecalho, json={
        "name": conta["usuario"]["nome"], "phone": conta["usuario"]["telefone"],
        "service": "Corte masculino", "barber": equipe["apelido"], "date": dia, "time": hora})
    assert reserva.status_code == 201, reserva.text

    depois = cliente.get("/api/publica/disponibilidade"
                         f"?servico_id={cortar['id']}&profissional_id={equipe['id']}&data={dia}").json()
    assert iso not in depois["profissionais"][0]["slots"], "o horário marcado continuou na grade"
    # sai o horário marcado e o seguinte (cai dentro do buffer de 5 min do atendimento)
    restantes = depois["profissionais"][0]["slots"]
    assert len(restantes) == len(antes["profissionais"][0]["slots"]) - 2, restantes[:3]
    assert restantes[0] != antes["profissionais"][0]["slots"][1], "o slot do buffer continuou na grade"

    repetida = cliente.post("/api/bookings", headers=cabecalho, json={
        "name": conta["usuario"]["nome"], "phone": conta["usuario"]["telefone"],
        "service": "Corte masculino", "barber": equipe["apelido"], "date": dia, "time": hora})
    assert repetida.status_code == 409
    assert repetida.json()["codigo"] == "horario_ocupado"


def test_horario_fora_da_grade_e_recusado_pela_api(cliente):
    equipe = barbeiro()
    dia, hora, _ = primeiro_slot_livre(cliente, servico("Corte masculino")["id"], equipe["id"])
    conta = cadastrar(cliente)
    cabecalho = {"Authorization": "Bearer " + conta["token"]}
    fora = cliente.post("/api/bookings", headers=cabecalho, json={
        "name": conta["usuario"]["nome"], "phone": conta["usuario"]["telefone"],
        "service": "Corte masculino", "barber": equipe["apelido"], "date": dia, "time": "14:07"})
    assert fora.status_code == 400, fora.text
    assert fora.json()["codigo"] == "horario_invalido"

    domingo = (datetime.now(FUSO).date() + timedelta(days=1))
    while domingo.weekday() != 6:
        domingo += timedelta(days=1)
    fechado = cliente.post("/api/bookings", headers=cabecalho, json={
        "name": conta["usuario"]["nome"], "phone": conta["usuario"]["telefone"],
        "service": "Corte masculino", "barber": equipe["apelido"],
        "date": domingo.isoformat(), "time": hora})
    assert fechado.status_code == 400, fechado.text
    assert fechado.json()["codigo"] == "horario_invalido"


def test_disponibilidade_de_varios_dias_traz_contagem_por_dia(cliente):
    equipe = barbeiro()
    cortar = servico("Corte masculino")
    hoje = datetime.now(FUSO).date()
    de, ate = hoje.isoformat(), (hoje + timedelta(days=6)).isoformat()
    resposta = cliente.get("/api/publica/disponibilidade"
                          f"?servico_id={cortar['id']}&profissional_id={equipe['id']}&de={de}&ate={ate}")
    assert resposta.status_code == 200, resposta.text
    dias = resposta.json()["dias"]
    assert [dia["data"] for dia in dias] == [(hoje + timedelta(days=n)).isoformat() for n in range(7)]
    for dia in dias:
        assert isinstance(dia["livres"], int)
        if dia["livres"]:
            assert dia["primeiro"] and dia["primeiro"].endswith("Z")
            assert dia["motivo_vazio"] is None
        else:
            assert dia["motivo_vazio"] and dia["motivo_texto"]
    domingo = next(dia for dia in dias if datetime.strptime(dia["data"], "%Y-%m-%d").weekday() == 6)
    assert domingo["motivo_vazio"] == agenda.LOJA_FECHADA


def test_disponibilidade_recusa_pedido_mal_formado(cliente):
    cortar = servico("Corte masculino")
    assert cliente.get(f"/api/publica/disponibilidade?servico_id={cortar['id']}").status_code == 400
    assert cliente.get(f"/api/publica/disponibilidade?servico_id={cortar['id']}&data=17/09/2026").status_code == 400
    resposta = cliente.get(f"/api/publica/disponibilidade?servico_id={cortar['id']}"
                           "&de=2026-09-01&ate=2026-10-15")
    assert resposta.status_code == 400 and resposta.json()["codigo"] == "validacao"
    assert cliente.get("/api/publica/disponibilidade?servico_id=99999&data=2027-01-01").status_code == 404
    equipe = barbeiro()
    outro = cliente.get(f"/api/publica/disponibilidade?servico_id={cortar['id']}"
                        f"&profissional_id={equipe['id'] + 999}&data=2027-01-01")
    assert outro.status_code == 404


def test_catalogo_e_equipe_publicos_nao_exigem_login(cliente):
    catalogo = cliente.get("/api/publica/servicos")
    assert catalogo.status_code == 200
    servicos = catalogo.json()["servicos"]
    assert any(item["nome"] == "Corte masculino" and item["preco"] == "R$ 45" for item in servicos)
    assert all(item["duracao"] and item["duracao_min"] for item in servicos)

    equipe = barbeiro(["Corte masculino"])
    resposta = cliente.get(f"/api/publica/equipe?servico_id={servico('Corte masculino')['id']}")
    assert resposta.status_code == 200
    profissionais = resposta.json()["profissionais"]
    assert all(item["id"] for item in profissionais)
    assert any(item["nome"] == equipe["nome"] and servico("Corte masculino")["id"] in item["servicos"]
               for item in profissionais)
    sem_barba = cliente.get(f"/api/publica/equipe?servico_id={servico('Barba')['id']}").json()["profissionais"]
    assert equipe["nome"] not in [item["nome"] for item in sem_barba]
