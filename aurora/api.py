"""API FastAPI do assistente (contrato do enunciado)."""
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from google.adk.apps import App
from google.adk.runners import Runner
from google.adk.sessions.sqlite_session_service import SqliteSessionService
from google.genai import types
from pydantic import BaseModel

from . import db
from .agents import aurora
from .config import APP_NAME, DB_SESSOES, USER_ID

CONFIRMACAO = "adk_request_confirmation"

session_service = SqliteSessionService(str(DB_SESSOES))
runner = Runner(
    app=App(name=APP_NAME, root_agent=aurora),
    session_service=session_service,
)
_locks: dict[str, asyncio.Lock] = {}


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.inicializar()
    yield


app = FastAPI(title="Residencial Aurora", lifespan=lifespan)


class NovaSessao(BaseModel):
    apartamento: str


class Mensagem(BaseModel):
    texto: str


class RespostaConfirmacao(BaseModel):
    id: str
    confirmado: bool


async def _sessao(session_id: str):
    s = await session_service.get_session(app_name=APP_NAME, user_id=USER_ID, session_id=session_id)
    if s is None:
        raise HTTPException(404, "Sessão não encontrada")
    return s


def _pendentes(session) -> list[dict]:
    """Confirmações pendentes = pedidos de confirmação sem resposta do usuário.

    Derivado dos eventos persistidos, então sobrevive a reinício da API.
    """
    pedidos: dict[str, dict] = {}
    for ev in session.events:
        for fc in ev.get_function_calls():
            if fc.name == CONFIRMACAO:
                original = (fc.args or {}).get("originalFunctionCall", {})
                pedidos[fc.id] = {
                    "id": fc.id,
                    "acao": original.get("name", ""),
                    "detalhes": original.get("args", {}),
                }
        if ev.author == "user":
            for fr in ev.get_function_responses():
                pedidos.pop(fr.id, None)
    return list(pedidos.values())


async def _executar(session_id: str, content: types.Content) -> dict:
    textos: list[str] = []
    async for ev in runner.run_async(user_id=USER_ID, session_id=session_id, new_message=content):
        if ev.author == "user" or not ev.content or ev.partial:
            continue
        if ev.get_function_calls() or ev.get_function_responses():
            continue
        textos += [p.text for p in ev.content.parts or [] if p.text and not p.thought]
    session = await _sessao(session_id)
    return {"resposta": "\n".join(textos).strip(), "confirmacoes_pendentes": _pendentes(session)}


def _lock(session_id: str) -> asyncio.Lock:
    return _locks.setdefault(session_id, asyncio.Lock())


@app.post("/sessoes", status_code=201)
async def criar_sessao(corpo: NovaSessao):
    # O apartamento é gravado aqui, uma única vez; as tools só leem do state.
    s = await session_service.create_session(
        app_name=APP_NAME, user_id=USER_ID, state={"apartamento": corpo.apartamento}
    )
    return {"session_id": s.id}


@app.post("/sessoes/{session_id}/mensagens")
async def enviar_mensagem(session_id: str, corpo: Mensagem):
    await _sessao(session_id)
    async with _lock(session_id):
        content = types.Content(role="user", parts=[types.Part(text=corpo.texto)])
        return await _executar(session_id, content)


@app.post("/sessoes/{session_id}/confirmacoes")
async def responder_confirmacao(session_id: str, corpo: RespostaConfirmacao):
    await _sessao(session_id)
    async with _lock(session_id):
        session = await _sessao(session_id)
        if corpo.id not in {p["id"] for p in _pendentes(session)}:
            raise HTTPException(409, "Não há confirmação pendente com esse id nesta sessão")
        content = types.Content(
            role="user",
            parts=[
                types.Part(
                    function_response=types.FunctionResponse(
                        id=corpo.id, name=CONFIRMACAO, response={"confirmed": corpo.confirmado}
                    )
                )
            ],
        )
        return await _executar(session_id, content)


@app.get("/sessoes/{session_id}/eventos")
async def eventos(session_id: str):
    s = await _sessao(session_id)
    return [e.model_dump(mode="json", exclude_none=True) for e in s.events]


@app.get("/apartamentos/{numero}/reservas")
async def reservas(numero: str):
    return db.reservas_do_apartamento(numero)


@app.get("/apartamentos/{numero}/visitantes")
async def visitantes(numero: str):
    return db.visitantes_do_apartamento(numero)
