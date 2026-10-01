# Residencial Aurora — assistente virtual (Google ADK)

API em Python (FastAPI + Google ADK 2.2.0) com um agente principal e três especialistas. O modelo conduz a conversa; as regras críticas vivem no código.

## Arquitetura

```
aurora/
  config.py       caminhos, modelo (GEMINI_MODEL), ids fixos
  db.py           SQLite de reservas e visitantes (índice único de reserva)
  regulamento.py  busca de artigos no regulamento
  tools.py        tools dos agentes (o apartamento vem sempre da sessão)
  agents.py       agente principal + especialistas
  api.py          rotas FastAPI, Runner/App, confirmações
  restaurar.py    restaura os dados iniciais
scripts/fluxo_simulado.py   teste do fluxo do avaliador com modelo simulado
```

Todos os especialistas são `sub_agents` do principal (transferência de controle do ADK). Motivo: com transferência, a retomada de uma confirmação chega ao agente que a pediu (o Runner entrega a resposta ao autor da chamada), e o especialista segue na conversa nas mensagens seguintes. Foi testado com sessão persistida em SQLite e depois de reiniciar a API.

| Agente | Responsabilidade | Tools | Acionamento |
|---|---|---|---|
| `aurora` (principal) | Conversa geral e roteamento. Não tem tools de dados nem o regulamento nas instruções. | — | Raiz do App |
| `reservas` | Reservar, cancelar, listar reservas e ver disponibilidade | `reservar_area`, `cancelar_reserva`, `listar_minhas_reservas`, `consultar_disponibilidade` | Transferência a partir do principal |
| `visitantes` | Autorizar e listar visitantes | `autorizar_visitante`, `listar_meus_visitantes` | Transferência |
| `regulamento` | Dúvidas sobre o regulamento, citando o artigo | `consultar_regulamento` | Transferência |

Separar por domínio mantém instruções e tools curtas por agente, e isola o regulamento (a parte cara em tokens) num único especialista que só o consulta por busca.

## Garantias

1. **Cobrança/acesso só com confirmação** — `aurora/tools.py`: `tool_reservar_area` e `tool_autorizar_visitante` são `FunctionTool(..., require_confirmation=...)`. `_exige_confirmacao_reserva` decide pela taxa em `dados/areas.json` (taxa > 0 e data livre); `autorizar_visitante` sempre exige. É o ADK, não o modelo, que bloqueia a execução. Em `aurora/api.py`, `_pendentes()` lê dos eventos persistidos os `adk_request_confirmation` sem resposta; `responder_confirmacao` devolve `409` se o `id` não está pendente (inclusive um já respondido) e, se está, envia ao Runner um `FunctionResponse` `adk_request_confirmation` com `{"confirmed": ...}`. Texto como "já confirmei" não gera essa resposta.
2. **Sessão pertence a um apartamento** — `aurora/api.py::criar_sessao` grava `state={"apartamento": ...}` uma única vez. Em `aurora/tools.py`, nenhuma tool recebe apartamento: todas usam `_apartamento(tool_context)` (lê `tool_context.state`). Cancelamento só casa reservas do próprio apartamento (`db.cancelar_reserva`) e responde só "não encontrada"; `db.data_ocupada` devolve apenas booleano, nunca o dono.
3. **Nada se perde no reinício** — sessões em `SqliteSessionService` (`aurora/api.py`, arquivo `var/sessoes.db`) e dados em `var/condominio.db` (`aurora/db.py`). A lista de confirmações pendentes é derivada dos eventos persistidos. A restauração é um comando separado e não roda na subida (só carrega os dados se o banco estiver vazio). Códigos de reserva são aleatórios (`RSV-` + 8 hex) com `PRIMARY KEY`, e reservas canceladas permanecem na tabela (`status='cancelada'`), então um código nunca é reutilizado.
4. **Regulamento consultado, não carregado** — `aurora/regulamento.py::buscar` divide o regulamento em artigos, pontua pela consulta e devolve só os artigos do capítulo mais relevante. Só o especialista `regulamento` tem a tool (`consultar_regulamento` em `aurora/tools.py`); `aurora/agents.py` não coloca o texto em nenhuma instrução.
5. **Dois moradores, uma reserva** — `aurora/db.py`: índice único parcial `ux_reserva_ativa ON reservas(area, data) WHERE status='ativa'`. `criar_reserva` faz o `INSERT` e trata `IntegrityError` devolvendo `None`; a tool responde `indisponivel` (HTTP 200, sem erro de servidor). A conferência prévia é só otimização; a exclusividade vale no instante da gravação. A conexão usa `busy_timeout`, então escritas concorrentes esperam em vez de falhar.

## Como rodar

Pré-requisitos: Python 3.12+, [uv](https://docs.astral.sh/uv/) e uma chave do Google AI Studio. Não há serviço externo (SQLite em arquivo, em `var/`).

```bash
cp .env.example .env     # preencha GOOGLE_API_KEY (GEMINI_MODEL é opcional; padrão gemini-2.5-flash)
uv sync
uv run python -m aurora.restaurar   # restaura reservas e visitantes (mantém as sessões)
uv run python -m aurora             # sobe a API em http://localhost:8000
```

Variáveis do `.env`: `GOOGLE_API_KEY` (obrigatória) e `GEMINI_MODEL` (opcional).

Para recomeçar do zero, inclusive sessões, apague a pasta `var/` e rode a restauração.

Teste da infraestrutura sem chamar o Gemini (confirmações, reinício, disputa):

```bash
GOOGLE_API_KEY=x PYTHONPATH=. uv run python scripts/fluxo_simulado.py
```
