#!/usr/bin/env python3
"""Valida o schema do Barbearia Magno e prova as regras críticas antes de existir código de app.

Roda contra um banco descartável (nunca toca data/magno.db) e verifica:
  1. docs/schema.sql executa limpo (tabelas, índices, seed)
  2. CHECKs de integridade funcionam (dia_semana, fim > inicio)
  3. a query de overbooking detecta conflito E buffer
  4. o índice único parcial impede dois atendimentos no mesmo instante
  5. duas escritas concorrentes no mesmo slot: uma passa, a outra falha
  6. o modelo suporta o cálculo de disponibilidade (grade - bloqueios - agendamentos)

Uso: python3 scripts/valida_schema.py
"""
import os
import sqlite3
import sys
import threading
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DB = "/tmp/magno-valida-schema.db"

ok = 0
falhou = 0


def checa(nome, condicao, detalhe=""):
    global ok, falhou
    if condicao:
        ok += 1
        print(f"  [OK] {nome}")
    else:
        falhou += 1
        print(f"  [FALHOU] {nome} {detalhe!r}")


def novo_banco():
    if os.path.exists(DB):
        os.remove(DB)
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.executescript((RAIZ / "docs" / "schema.sql").read_text(encoding="utf-8"))
    return con


# ------------------------------------------------------------------ 1 e 2
print("1) schema + integridade")
con = novo_banco()
tabelas = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
checa("schema cria as 11 tabelas de domínio", len(tabelas - {"sqlite_sequence"}) == 11, tabelas)
checa("seed de configuracoes", con.execute("SELECT COUNT(*) FROM configuracoes").fetchone()[0] == 12)
checa("seed de horarios (7 dias)", con.execute("SELECT COUNT(*) FROM horarios").fetchone()[0] == 7)
checa("seed de servicos", con.execute("SELECT COUNT(*) FROM servicos").fetchone()[0] == 4)

try:
    con.execute("INSERT INTO horarios (dia_semana,abre,fecha) VALUES (7,'09:00','10:00')")
    checa("CHECK dia_semana rejeita 7", False)
except sqlite3.IntegrityError:
    checa("CHECK dia_semana rejeita 7", True)

con.execute("INSERT INTO usuarios (nome,telefone,senha_hash,papel) VALUES ('Cliente','5513997630784','x','cliente')")
con.execute("INSERT INTO usuarios (nome,telefone,senha_hash,papel) VALUES ('Rafael','5513991112222','x','barbeiro')")
con.execute("INSERT INTO profissionais (usuario_id,apelido) VALUES (2,'Rafa')")
try:
    con.execute("""INSERT INTO servico_profissional (servico_id, profissional_id) VALUES (999,1)""")
    checa("FK de servico_profissional ativa", False)
except sqlite3.IntegrityError:
    checa("FK de servico_profissional ativa", True)
con.commit()

# ------------------------------------------------------------------ 3
print("\n2) overbooking (query de overlap + buffer)")
con.execute("""INSERT INTO agendamentos
  (codigo,cliente_id,profissional_id,servico_id,inicio,fim,duracao_min,preco_centavos,status)
  VALUES ('mg-aaa11111',1,1,1,'2026-09-15T13:00:00Z','2026-09-15T13:35:00Z',30,4500,'agendado')""")
con.commit()

OVERLAP = """SELECT 1 FROM agendamentos
 WHERE profissional_id = ? AND status IN ('agendado','confirmado','concluido')
   AND inicio < ? AND fim > ? LIMIT 1"""

checa("slot exatamente igual → conflito", con.execute(OVERLAP, (1, "2026-09-15T13:35:00Z", "2026-09-15T13:00:00Z")).fetchone() is not None)
checa("slot seguinte da grade (13:30) cai no buffer → conflito", con.execute(OVERLAP, (1, "2026-09-15T14:00:00Z", "2026-09-15T13:30:00Z")).fetchone() is not None)
checa("slot exatamente em `fim` (13:35, buffer já embutido) → livre", con.execute(OVERLAP, (1, "2026-09-15T14:05:00Z", "2026-09-15T13:35:00Z")).fetchone() is None)
checa("slot de manhã → livre", con.execute(OVERLAP, (1, "2026-09-15T12:00:00Z", "2026-09-15T11:30:00Z")).fetchone() is None)
con.execute("UPDATE agendamentos SET status='cancelado_cliente' WHERE codigo='mg-aaa11111'")
checa("cancelado libera o horário", con.execute(OVERLAP, (1, "2026-09-15T13:35:00Z", "2026-09-15T13:00:00Z")).fetchone() is None)
con.execute("UPDATE agendamentos SET status='agendado' WHERE codigo='mg-aaa11111'")
con.commit()

# ------------------------------------------------------------------ 4
print("\n3) trava dura contra duplicidade (índice único parcial)")
try:
    con.execute("""INSERT INTO agendamentos
      (codigo,cliente_id,profissional_id,servico_id,inicio,fim,duracao_min,preco_centavos,status)
      VALUES ('mg-bbb22222',1,1,2,'2026-09-15T13:00:00Z','2026-09-15T13:30:00Z',30,3500,'agendado')""")
    checa("dois atendimentos ativos no mesmo instante → bloqueado", False)
except sqlite3.IntegrityError:
    checa("dois atendimentos ativos no mesmo instante → bloqueado", True)
# PITFALL REAL (descoberto por este script): em Python, o sqlite3 deixa a transação ABERTA
# depois de uma exceção — sem rollback, a conexão segura o lock e qualquer outra conexão
# recebe "database is locked". Sempre rollback() após erro esperado.
con.rollback()

# ------------------------------------------------------------------ 5
print("\n4) corrida de escrita (duas threads no mesmo slot)")
resultado = []
barreira = threading.Barrier(2)


def tentar(rotulo):
    c = sqlite3.connect(DB, timeout=5)
    c.execute("PRAGMA foreign_keys=ON")
    barreira.wait()
    try:
        c.execute("BEGIN IMMEDIATE")
        if c.execute(OVERLAP, (1, "2026-09-15T15:35:00Z", "2026-09-15T15:00:00Z")).fetchone():
            resultado.append((rotulo, "409 conflito(overlap)"))
        else:
            c.execute("""INSERT INTO agendamentos
              (codigo,cliente_id,profissional_id,servico_id,inicio,fim,duracao_min,preco_centavos,status)
              VALUES (?,1,1,1,'2026-09-15T15:00:00Z','2026-09-15T15:35:00Z',30,4500,'agendado')""",
                      (f"mg-c{rotulo}3333",))
            resultado.append((rotulo, "201 criado"))
        c.commit()
    except sqlite3.IntegrityError:
        resultado.append((rotulo, "409 conflito(indice)"))
    except sqlite3.OperationalError as e:
        resultado.append((rotulo, f"retry({e})"))
    finally:
        c.close()


threads = [threading.Thread(target=tentar, args=(i,)) for i in (1, 2)]
[t.start() for t in threads]
[t.join() for t in threads]
criados = [r for r in resultado if r[1].startswith("201")]
checa(f"uma escrita vence e a outra é recusada ({resultado})", len(criados) == 1)
checa("nenhum horário duplicado no banco",
      con.execute("""SELECT COUNT(*) FROM (SELECT profissional_id,inicio FROM agendamentos
                     WHERE status IN ('agendado','confirmado','concluido')
                     GROUP BY profissional_id,inicio HAVING COUNT(*)>1)""").fetchone()[0] == 0)

# ------------------------------------------------------------------ 6
print("\n5) motor de disponibilidade suporta o cálculo (grade - bloqueios - agendamentos)")
con.execute("INSERT INTO bloqueios (profissional_id,inicio,fim,motivo) VALUES (1,'2026-09-16T15:00:00Z','2026-09-16T16:00:00Z','almoço')")
con.execute("INSERT INTO excecoes (data,fechado,motivo) VALUES ('2026-09-17',1,'feriado')")
con.commit()
ocupado = con.execute("""SELECT inicio,fim FROM agendamentos
   WHERE profissional_id=1 AND status IN ('agendado','confirmado','concluido')
     AND inicio >= '2026-09-16T00:00:00Z' AND inicio < '2026-09-17T00:00:00Z'
 UNION ALL
 SELECT inicio,fim FROM bloqueios WHERE profissional_id=1
   AND inicio < '2026-09-17T00:00:00Z' AND fim > '2026-09-16T00:00:00Z'""").fetchall()
checa("ocupação de 16/09 (agenda + bloqueio) em 1 query", len(ocupado) == 1, [dict(r) for r in ocupado])
checa("17/09 é feriado (exceção fechado=1)",
      con.execute("SELECT fechado FROM excecoes WHERE data='2026-09-17'").fetchone()[0] == 1)
cfg = {r["chave"]: r["valor"] for r in con.execute("SELECT chave,valor FROM configuracoes")}
checa("regras de negócio lidas do banco, não do código", cfg["slot_min"] == "30" and cfg["cancelamento_limite_h"] == "2")

con.close()
os.remove(DB)
print(f"\n=== {ok} verificações OK, {falhou} FALHAS ===")
sys.exit(1 if falhou else 0)
