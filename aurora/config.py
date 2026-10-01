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

MODELO = os.getenv("GEMINI_MODEL") or "gemini-2.5-flash"
