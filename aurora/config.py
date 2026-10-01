import os
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent
load_dotenv(RAIZ / ".env")

DADOS = RAIZ / "dados"
VAR = RAIZ / "var"
VAR.mkdir(exist_ok=True)

DB_CONDOMINIO = VAR / "condominio.db"
DB_SESSOES = VAR / "sessoes.db"

APP_NAME = "residencial_aurora"
USER_ID = "morador"

from google.adk.models.google_llm import Gemini
from google.genai import types

# Modelo de cada agente (sobrescrevível pelo .env). Modelos diferentes também
# espalham a cota por modelo do plano gratuito.
PADROES = {
    "AURORA": "gemini-3.1-flash-lite",
    "RESERVAS": "gemini-3.6-flash",
    "VISITANTES": "gemini-flash-lite-latest",
    "REGULAMENTO": "gemini-3.5-flash-lite",
}


def novo_modelo(agente: str) -> Gemini:
    nome = os.getenv(f"MODELO_{agente}") or os.getenv("GEMINI_MODEL") or PADROES[agente]
    # Retentativas com backoff para erros transitórios (503) da API.
    return Gemini(
        model=nome,
        retry_options=types.HttpRetryOptions(attempts=4, initial_delay=2, max_delay=20),
    )
