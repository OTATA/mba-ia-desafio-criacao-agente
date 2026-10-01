"""Tools do assistente.

Regra de ouro: nenhuma tool recebe o apartamento como parâmetro. O apartamento
vem de `tool_context.state["apartamento"]`, gravado uma única vez na criação da
sessão pela API. O modelo não tem como escolher nem alterar esse valor.
"""
from datetime import date

from google.adk.tools import FunctionTool, ToolContext

from . import db, regulamento


def _apartamento(tool_context: ToolContext) -> str | None:
    return tool_context.state.get("apartamento")


def _data_valida(data: str) -> bool:
    try:
        date.fromisoformat(data)
        return len(data) == 10
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------- reservas

def listar_minhas_reservas(tool_context: ToolContext) -> dict:
    """Lista as reservas ativas do morador desta conversa (código, área e data)."""
    apto = _apartamento(tool_context)
    if not apto:
        return {"status": "erro", "mensagem": "Sessão sem apartamento."}
    return {"status": "ok", "reservas": db.reservas_do_apartamento(apto)}


def consultar_disponibilidade(area: str, data: str) -> dict:
    """Informa se uma área comum está livre ou ocupada em uma data.

    Args:
        area: id da área: "salao-de-festas", "churrasqueira" ou "quadra".
        data: data no formato AAAA-MM-DD.
    """
    if area not in db.areas():
        return {"status": "erro", "mensagem": f"Área desconhecida. Opções: {', '.join(db.areas())}."}
    if not _data_valida(data):
        return {"status": "erro", "mensagem": "Data inválida. Use AAAA-MM-DD."}
    return {"status": "ok", "area": area, "data": data, "disponivel": not db.data_ocupada(area, data)}


def _exige_confirmacao_reserva(area: str, data: str = "", **_) -> bool:
    """Reserva de área com taxa > 0 gera cobrança, então exige confirmação.

    Data já ocupada não gera cobrança (a tool recusa), então não pede confirmação.
    A decisão final de exclusividade continua no INSERT (db.criar_reserva).
    """
    a = db.areas().get(area)
    return bool(a and a["taxa"] > 0 and _data_valida(data) and not db.data_ocupada(area, data))


def reservar_area(area: str, data: str, tool_context: ToolContext) -> dict:
    """Reserva uma área comum para o morador desta conversa.

    Áreas com taxa geram cobrança e só executam depois que o morador confirma
    pelo sistema. Se a data já estiver ocupada, a reserva é recusada.

    Args:
        area: id da área: "salao-de-festas", "churrasqueira" ou "quadra".
        data: data da reserva no formato AAAA-MM-DD.
    """
    apto = _apartamento(tool_context)
    if not apto:
        return {"status": "erro", "mensagem": "Sessão sem apartamento."}
    areas = db.areas()
    if area not in areas:
        return {"status": "erro", "mensagem": f"Área desconhecida. Opções: {', '.join(areas)}."}
    if not _data_valida(data):
        return {"status": "erro", "mensagem": "Data inválida. Use AAAA-MM-DD."}
    # A exclusividade é decidida pelo índice único no INSERT, não por conferência prévia.
    codigo = db.criar_reserva(apto, area, data)
    if codigo is None:
        return {"status": "indisponivel", "mensagem": "Essa área já está reservada nessa data."}
    taxa = areas[area]["taxa"]
    return {"status": "ok", "codigo": codigo, "area": area, "data": data, "taxa_cobrada": taxa}


def cancelar_reserva(
    tool_context: ToolContext, area: str = "", data: str = "", codigo: str = ""
) -> dict:
    """Cancela uma reserva do morador desta conversa, sem confirmação.

    Só cancela reservas do próprio apartamento. Informe o código, ou a área e a data.

    Args:
        area: id da área (opcional se informar o código).
        data: data da reserva AAAA-MM-DD (opcional se informar o código).
        codigo: código da reserva, como RSV-1234 (opcional).
    """
    apto = _apartamento(tool_context)
    if not apto:
        return {"status": "erro", "mensagem": "Sessão sem apartamento."}
    if not (codigo or (area and data)):
        return {"status": "erro", "mensagem": "Informe o código, ou a área e a data."}
    r = db.cancelar_reserva(apto, area or None, data or None, codigo or None)
    if r is None or "ambigua" in r:
        return {"status": "nao_encontrada", "mensagem": "Você não tem reserva ativa com esses dados."}
    return {"status": "ok", "cancelada": r}


# ---------------------------------------------------------------- visitantes

def listar_meus_visitantes(tool_context: ToolContext) -> dict:
    """Lista os visitantes autorizados pelo morador desta conversa."""
    apto = _apartamento(tool_context)
    if not apto:
        return {"status": "erro", "mensagem": "Sessão sem apartamento."}
    return {"status": "ok", "visitantes": db.visitantes_do_apartamento(apto)}


def _sempre(**_) -> bool:
    return True


def autorizar_visitante(nome: str, data: str, tool_context: ToolContext) -> dict:
    """Autoriza a entrada de um visitante no prédio, para o morador desta conversa.

    Libera acesso ao prédio, então só executa depois que o morador confirma
    pelo sistema (não pela conversa).

    Args:
        nome: nome completo do visitante.
        data: data da visita no formato AAAA-MM-DD.
    """
    apto = _apartamento(tool_context)
    if not apto:
        return {"status": "erro", "mensagem": "Sessão sem apartamento."}
    nome = " ".join((nome or "").split())
    if not nome:
        return {"status": "erro", "mensagem": "Informe o nome do visitante."}
    if not _data_valida(data):
        return {"status": "erro", "mensagem": "Data inválida. Use AAAA-MM-DD."}
    novo = db.autorizar_visitante(apto, nome, data)
    return {"status": "ok", "nome": nome, "data": data, "ja_estava_autorizado": not novo}


# ---------------------------------------------------------------- regulamento

def consultar_regulamento(consulta: str) -> dict:
    """Busca no regulamento interno os artigos relevantes para a consulta.

    Args:
        consulta: palavras-chave do assunto, ex.: "piscina horário domingo".
    """
    trecho = regulamento.buscar(consulta)
    if not trecho:
        return {"status": "nada_encontrado", "mensagem": "Nenhum artigo encontrado. Tente outras palavras-chave."}
    return {"status": "ok", "trecho": trecho}


# Tools que mudam dados ou liberam acesso passam por FunctionTool com confirmação.
tool_reservar_area = FunctionTool(reservar_area, require_confirmation=_exige_confirmacao_reserva)
tool_autorizar_visitante = FunctionTool(autorizar_visitante, require_confirmation=_sempre)
