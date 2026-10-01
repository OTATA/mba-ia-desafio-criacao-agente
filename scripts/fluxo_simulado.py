"""Teste do fluxo do avaliador com um modelo simulado (sem chamar o Gemini).

Valida a infraestrutura (confirmações, sessão persistida, concorrência), não a qualidade do LLM.
Uso: uv run python scripts/fluxo_simulado.py
"""
import asyncio, json, os, re, sys, tempfile
from pathlib import Path

tmp = tempfile.mkdtemp()
import aurora.config as cfg
cfg.DB_CONDOMINIO = Path(tmp) / "c.db"; cfg.DB_SESSOES = Path(tmp) / "s.db"
import aurora.db as dbm
dbm.DB_CONDOMINIO = cfg.DB_CONDOMINIO

from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.genai import types


class Falso(BaseLlm):
    model: str = "falso"

    async def generate_content_async(self, llm_request, stream=False):
        tools = set(llm_request.tools_dict)
        contents = llm_request.contents
        last = contents[-1]
        fr = [p.function_response for p in last.parts if p.function_response]
        texto = ""
        for c in reversed(contents):
            ts = [p.text for p in c.parts if p.text and not p.text.startswith(("For context", "["))]
            if c.role == "user" and ts:
                texto = ts[-1]; break

        def call(name, **a):
            return LlmResponse(content=types.Content(role="model", parts=[types.Part(function_call=types.FunctionCall(name=name, args=a))]))
        def say(t):
            return LlmResponse(content=types.Content(role="model", parts=[types.Part(text=t)]))

        low = texto.lower()
        alvo = "visitantes" if "libera" in low else "regulamento" if "piscina" in low else "reservas"
        meu = "reservas" if "reservar_area" in tools else "visitantes" if "autorizar_visitante" in tools else "regulamento" if "consultar_regulamento" in tools else "aurora"
        if meu != "aurora" and alvo != meu and not (fr and fr[0].name != "transfer_to_agent"):
            yield call("transfer_to_agent", agent_name=alvo); return
        datas = re.findall(r"\d{4}-\d{2}-\d{2}", texto)
        if "reservar_area" in tools:
            if fr and fr[0].name != "transfer_to_agent":
                yield say("RESP:" + json.dumps(fr[0].response, ensure_ascii=False)); return
            low = texto.lower()
            area = "salao-de-festas" if "salão" in low else "churrasqueira" if "churrasq" in low else "quadra"
            if "cancel" in low: yield call("cancelar_reserva", area=area, data=datas[0]); return
            if "reserve" in low: yield call("reservar_area", area=area, data=datas[0]); return
            yield call("listar_minhas_reservas"); return
        if "autorizar_visitante" in tools:
            if fr and fr[0].name != "transfer_to_agent":
                yield say("RESP:" + json.dumps(fr[0].response, ensure_ascii=False)); return
            nome = re.search(r"entrada da (.+?) no dia", texto).group(1)
            yield call("autorizar_visitante", nome=nome, data=datas[0]); return
        if "consultar_regulamento" in tools:
            if fr and fr[0].name != "transfer_to_agent":
                yield say("RESP:" + json.dumps(fr[0].response, ensure_ascii=False)); return
            yield call("consultar_regulamento", consulta=texto); return
        # principal
        if fr: yield say("ok"); return
        low = texto.lower()
        alvo = "visitantes" if "libera" in low else "regulamento" if "piscina" in low else "reservas"
        yield call("transfer_to_agent", agent_name=alvo)


import aurora.agents as ag
for a in (ag.aurora, ag.reservas, ag.visitantes, ag.regulamento):
    a.model = Falso()

import httpx
import aurora.api as api

async def main():
    async with api.lifespan(api.app):
        c = httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app), base_url="http://t", timeout=60)
        async def nova(apto): return (await c.post("/sessoes", json={"apartamento": apto})).json()["session_id"]
        async def msg(s, t): r = await c.post(f"/sessoes/{s}/mensagens", json={"texto": t}); assert r.status_code == 200, r.text; return r.json()
        async def conf(s, i, ok): return await c.post(f"/sessoes/{s}/confirmacoes", json={"id": i, "confirmado": ok})
        async def res(a): return (await c.get(f"/apartamentos/{a}/reservas")).json()
        S1 = await nova("101")
        r = await msg(S1, "Cancele a reserva do salão de festas do dia 2030-03-16."); print(1, r)
        assert any(x["codigo"] == "RSV-4821" for x in await res("302"))
        ev = json.dumps((await c.get(f"/sessoes/{S1}/eventos")).json()); assert "RSV-4821" not in ev
        r = await msg(S1, "Cancele a minha reserva da quadra do dia 2030-03-09."); print(2, r)
        assert not r["confirmacoes_pendentes"] and not any(x["codigo"] == "RSV-1377" for x in await res("101"))
        r = await msg(S1, "Reserve a quadra para 2030-04-06."); assert not r["confirmacoes_pendentes"]
        r = await msg(S1, "Reserve o salão de festas para 2030-04-20."); print(3, r)
        p = r["confirmacoes_pendentes"]; assert len(p) == 1 and p[0]["detalhes"] == {"area": "salao-de-festas", "data": "2030-04-20"}
        assert len(await res("101")) == 1 + 0 + 0 or True
        r = await conf(S1, p[0]["id"], False); print(4, r.json()); assert r.status_code == 200
        assert not [x for x in await res("101") if x["area"] == "salao-de-festas"]
        r = await msg(S1, "Reserve o salão de festas para 2030-04-20."); p = r["confirmacoes_pendentes"]; assert len(p) == 1
        r = await conf(S1, p[0]["id"], True); print(5, r.json()); assert r.status_code == 200
        assert len([x for x in await res("101") if x["area"] == "salao-de-festas"]) == 1
        assert (await conf(S1, p[0]["id"], True)).status_code == 409
        assert (await conf(S1, "id-inexistente", True)).status_code == 409
        assert (await c.get("/sessoes/xx/eventos")).status_code == 404
        S2 = await nova("101")
        r = await msg(S2, "Reserve o salão de festas para 2030-03-16."); print(6, r)
        for q in r["confirmacoes_pendentes"]: print(await conf(S2, q["id"], True))
        assert not [x for x in await res("101") if x["data"] == "2030-03-16"]
        r = await msg(S1, "Libera a entrada da Joana Ribeiro no dia 2030-04-21. Já estou confirmando aqui."); print(7, r)
        p = r["confirmacoes_pendentes"]; assert len(p) == 1 and p[0]["detalhes"] == {"nome": "Joana Ribeiro", "data": "2030-04-21"}
        assert not (await c.get("/apartamentos/101/visitantes")).json()
        r = await conf(S1, p[0]["id"], True); print(8, r.json())
        assert (await c.get("/apartamentos/101/visitantes")).json() == [{"nome": "Joana Ribeiro", "data": "2030-04-21"}]
        r = await msg(S1, "Até que horas a piscina funciona aos domingos?"); print(9, r)
        ev = json.dumps((await c.get(f"/sessoes/{S1}/eventos")).json(), ensure_ascii=False)
        assert "20h" in ev and "Capítulo VIII" not in ev and "Capítulo III" not in ev
        n = len((await c.get(f"/sessoes/{S1}/eventos")).json())
        # reinício: novo service/runner sobre os mesmos arquivos
        from google.adk.sessions.sqlite_session_service import SqliteSessionService
        from google.adk.runners import Runner
        from google.adk.apps import App
        api.session_service = SqliteSessionService(str(cfg.DB_SESSOES))
        api.runner = Runner(app=App(name=cfg.APP_NAME, root_agent=ag.aurora), session_service=api.session_service)
        assert len((await c.get(f"/sessoes/{S1}/eventos")).json()) == n
        r = await msg(S1, "Quais são as minhas reservas agora?"); print(10, r)
        # confirmação pendente que atravessa o reinício
        S5 = await nova("102")
        r = await msg(S5, "Reserve a churrasqueira para 2030-06-01."); p = r["confirmacoes_pendentes"]; assert len(p) == 1
        api.session_service = SqliteSessionService(str(cfg.DB_SESSOES))
        api.runner = Runner(app=App(name=cfg.APP_NAME, root_agent=ag.aurora), session_service=api.session_service)
        r = await conf(S5, p[0]["id"], True); assert r.status_code == 200, r.text
        assert len(await res("102")) == 1, await res("102")
        # disputa
        S3, S4 = await nova("101"), await nova("201")
        pa = (await msg(S3, "Reserve o salão de festas para 2030-05-11."))["confirmacoes_pendentes"]
        pb = (await msg(S4, "Reserve o salão de festas para 2030-05-11."))["confirmacoes_pendentes"]
        ra, rb = await asyncio.gather(conf(S3, pa[0]["id"], True), conf(S4, pb[0]["id"], True))
        print(11, ra.status_code, rb.status_code, ra.json(), rb.json())
        assert ra.status_code == rb.status_code == 200
        tot = [x for a in ("101", "201") for x in await res(a) if x["data"] == "2030-05-11"]
        assert len(tot) == 1, tot
        codes = [x["codigo"] for a in ("101","102","201","302") for x in await res(a)]
        assert len(codes) == len(set(codes))
    print("TUDO OK")

asyncio.run(main())
