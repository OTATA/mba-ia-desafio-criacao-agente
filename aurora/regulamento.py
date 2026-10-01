"""Busca no regulamento: devolve só os artigos relevantes, nunca o texto todo."""
import math
import re
import unicodedata
from functools import lru_cache

from .config import DADOS

STOP = set(
    "a o as os um uma de da do das dos em no na nos nas por para com que e ou se ao aos "
    "qual quais quando como onde ha eh sao ser tem ter pode posso podem meu minha seu sua "
    "ate sobre mais menos muito ja nao sim quero queria gostaria saber qual horario".split()
) - {"horario"}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFD", s.lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def _tokens(s: str) -> list[str]:
    toks = [t for t in re.findall(r"[a-z0-9]+", _norm(s)) if t not in STOP and len(t) > 1]
    return [t[:-1] if t.endswith("s") and len(t) > 3 else t for t in toks]


@lru_cache(maxsize=1)
def _artigos() -> list[dict]:
    texto = (DADOS / "regulamento.md").read_text(encoding="utf-8")
    capitulo = ""
    artigos: list[dict] = []
    atual: list[str] | None = None
    for linha in texto.splitlines():
        if linha.startswith("## "):
            capitulo = linha[3:].strip()
            atual = None
        elif linha.startswith("**Art."):
            atual = [linha]
            artigos.append({"capitulo": capitulo, "linhas": atual})
        elif atual is not None and linha.strip():
            atual.append(linha)
    out = []
    for a in artigos:
        corpo = "\n".join(a["linhas"])
        out.append({"capitulo": a["capitulo"], "texto": corpo, "toks": _tokens(corpo + " " + a["capitulo"])})
    return out


def buscar(consulta: str, max_artigos: int = 4) -> str:
    arts = _artigos()
    q = set(_tokens(consulta))
    if not q:
        return ""
    n = len(arts)
    df: dict[str, int] = {}
    for a in arts:
        for t in set(a["toks"]):
            df[t] = df.get(t, 0) + 1

    def pontos(a):
        cont = {}
        for t in a["toks"]:
            cont[t] = cont.get(t, 0) + 1
        return sum(math.log(1 + n / df[t]) * (1 + math.log(c)) for t, c in cont.items() if t in q)

    ranque = sorted(((pontos(a), i) for i, a in enumerate(arts)), reverse=True)
    if not ranque or ranque[0][0] <= 0:
        return ""
    melhor = arts[ranque[0][1]]["capitulo"]
    # Só artigos do capítulo do melhor resultado: nada de outros assuntos no histórico.
    escolhidos = [
        i for s, i in ranque if s > 0 and arts[i]["capitulo"] == melhor
    ][:max_artigos]
    escolhidos.sort()
    return f"{melhor}\n\n" + "\n\n".join(arts[i]["texto"] for i in escolhidos)
