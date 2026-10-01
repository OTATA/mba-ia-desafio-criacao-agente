"""Armazenamento dos dados do condomínio (reservas e visitantes) em SQLite.

A exclusividade de reserva (uma ativa por área/data) é garantida por um índice
único parcial: o banco recusa a segunda gravação, não importa o que foi
conferido antes.
"""
import json
import sqlite3
import uuid
from contextlib import contextmanager

from .config import DADOS, DB_CONDOMINIO

SCHEMA = """
CREATE TABLE IF NOT EXISTS reservas (
    codigo TEXT PRIMARY KEY,
    apartamento TEXT NOT NULL,
    area TEXT NOT NULL,
    data TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ativa'
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_reserva_ativa
    ON reservas (area, data) WHERE status = 'ativa';
CREATE TABLE IF NOT EXISTS visitantes (
    apartamento TEXT NOT NULL,
    nome TEXT NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (apartamento, nome, data)
);
"""


@contextmanager
def conexao():
    con = sqlite3.connect(DB_CONDOMINIO, timeout=30, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=30000")
    try:
        yield con
    finally:
        con.close()


def inicializar():
    """Cria as tabelas e, se o banco é novo, carrega os dados iniciais."""
    with conexao() as con:
        con.executescript(SCHEMA)
        vazio = con.execute("SELECT COUNT(*) FROM reservas").fetchone()[0] == 0 and (
            con.execute("SELECT COUNT(*) FROM visitantes").fetchone()[0] == 0
        )
    if vazio:
        restaurar()


def _json(nome):
    return json.loads((DADOS / nome).read_text(encoding="utf-8"))


def restaurar():
    """Volta reservas e visitantes ao estado de dados/*.json."""
    with conexao() as con:
        con.executescript(SCHEMA)
        con.execute("BEGIN IMMEDIATE")
        con.execute("DELETE FROM reservas")
        con.execute("DELETE FROM visitantes")
        for r in _json("reservas.json"):
            con.execute(
                "INSERT INTO reservas (codigo, apartamento, area, data) VALUES (?,?,?,?)",
                (r["codigo"], r["apartamento"], r["area"], r["data"]),
            )
        for v in _json("visitantes.json"):
            con.execute(
                "INSERT OR IGNORE INTO visitantes (apartamento, nome, data) VALUES (?,?,?)",
                (v["apartamento"], v["nome"], v["data"]),
            )
        con.execute("COMMIT")


def areas() -> dict[str, dict]:
    return {a["id"]: a for a in _json("areas.json")}


def apartamento_existe(numero: str) -> bool:
    return any(a["numero"] == numero for a in _json("apartamentos.json"))


def reservas_do_apartamento(apartamento: str) -> list[dict]:
    with conexao() as con:
        rows = con.execute(
            "SELECT codigo, area, data FROM reservas WHERE apartamento=? AND status='ativa' "
            "ORDER BY data, codigo",
            (apartamento,),
        ).fetchall()
    return [dict(r) for r in rows]


def visitantes_do_apartamento(apartamento: str) -> list[dict]:
    with conexao() as con:
        rows = con.execute(
            "SELECT nome, data FROM visitantes WHERE apartamento=? ORDER BY data, nome",
            (apartamento,),
        ).fetchall()
    return [dict(r) for r in rows]


def data_ocupada(area: str, data: str) -> bool:
    """Só diz se está ocupada; nunca de quem é a reserva."""
    with conexao() as con:
        return (
            con.execute(
                "SELECT 1 FROM reservas WHERE area=? AND data=? AND status='ativa'",
                (area, data),
            ).fetchone()
            is not None
        )


def criar_reserva(apartamento: str, area: str, data: str) -> str | None:
    """Grava a reserva. Devolve o código, ou None se a data já está ocupada.

    A exclusividade vem do índice único parcial `ux_reserva_ativa`: se outra
    reserva entrou entre a conferência e este INSERT, o banco recusa.
    """
    for _ in range(10):
        codigo = f"RSV-{uuid.uuid4().hex[:8].upper()}"
        with conexao() as con:
            try:
                con.execute(
                    "INSERT INTO reservas (codigo, apartamento, area, data) VALUES (?,?,?,?)",
                    (codigo, apartamento, area, data),
                )
                return codigo
            except sqlite3.IntegrityError as e:
                if "reservas.codigo" in str(e):
                    continue  # colisão de código (improvável): gera outro
                return None  # área/data já ocupada
    raise RuntimeError("não foi possível gerar um código de reserva único")


def cancelar_reserva(apartamento: str, area: str | None, data: str | None, codigo: str | None) -> dict | None:
    """Cancela uma reserva ativa do próprio apartamento. None se não achar."""
    with conexao() as con:
        con.execute("BEGIN IMMEDIATE")
        sql = "SELECT codigo, area, data FROM reservas WHERE apartamento=? AND status='ativa'"
        params: list = [apartamento]
        if codigo:
            sql += " AND codigo=?"
            params.append(codigo.strip().upper())
        if area:
            sql += " AND area=?"
            params.append(area)
        if data:
            sql += " AND data=?"
            params.append(data)
        rows = con.execute(sql, params).fetchall()
        if len(rows) != 1:
            con.execute("ROLLBACK")
            return {"ambigua": len(rows)} if rows else None
        r = rows[0]
        con.execute("UPDATE reservas SET status='cancelada' WHERE codigo=?", (r["codigo"],))
        con.execute("COMMIT")
        return dict(r)


def autorizar_visitante(apartamento: str, nome: str, data: str) -> bool:
    with conexao() as con:
        cur = con.execute(
            "INSERT OR IGNORE INTO visitantes (apartamento, nome, data) VALUES (?,?,?)",
            (apartamento, nome, data),
        )
        return cur.rowcount == 1
