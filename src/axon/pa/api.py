"""
pa/api.py — API HTTP do Principal Agent.

Endpoints:
  POST /run    → one-shot query, retorna resposta final
  POST /chat   → turno de sessão interativa
  GET  /health → status do servidor

Fluxo de idioma (bordas):
  1. endpoint detecta idioma da query do usuário
  2. traduz query para inglês antes de passar ao PA
  3. PA e todos os componentes internos operam em inglês
  4. resposta final é traduzida de volta para o idioma do usuário

Isso mantém toda a comunicação interna do Axon em inglês —
logs, traces, AgentState, ConversationHistory — independente
do idioma do usuário.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from axon.config import read_config
from axon.pa.agent import PrincipalAgent

logger = logging.getLogger(__name__)


app = FastAPI(
    title="Axon Principal Agent",
    version="0.1.0",
    docs_url="/docs",
)

# instância global — carregada no startup
_agent: PrincipalAgent | None = None


@app.on_event("startup")
async def startup() -> None:
    global _agent
    try:
        config = read_config()
        _agent = PrincipalAgent(config.pa)
        logger.info("[PA API] started — model: %s", config.pa.llm.model)
    except FileNotFoundError:
        logger.error("[PA API] axon.config.json not found — run 'axon init' first")
        raise


def _get_agent() -> PrincipalAgent:
    if _agent is None:
        raise HTTPException(status_code=503, detail="Agent not initialized")
    return _agent


# ── Modelos de request/response 
# Mover para outro lugar depois 

class RunRequest(BaseModel):
    query:      str
    session_id: str | None = None


class ChatRequest(BaseModel):
    query:      str
    session_id: str | None = None


class RunResponse(BaseModel):
    response:    str
    session_id:  str | None = None
    language:    str         # idioma detectado da query original


class HealthResponse(BaseModel):
    status: str
    model:  str


# Para garantir consistência na linguagem, ao invés de traduzir internamente 
# "nós traduzimos antes de sair"
def _detect_language(text: str) -> str:
    """
    Detecta o idioma do texto.
    Retorna nome legível (ex: 'Portuguese', 'English').
    Fallback para 'English' em queries curtas ou se langdetect não instalado.
    """
    if len(text.strip()) < 8:
        return "English"
    try:
        from langdetect import detect, DetectorFactory
        DetectorFactory.seed = 0
        _LANG_NAMES = {
            "pt": "Portuguese", "en": "English", "es": "Spanish",
            "fr": "French",     "de": "German",  "it": "Italian",
            "zh-cn": "Chinese", "ja": "Japanese","ko": "Korean",
            "ar": "Arabic",
        }
        return _LANG_NAMES.get(detect(text), "English")
    except Exception:
        return "English"


def _translate(text: str, target_language: str, agent: PrincipalAgent) -> str:
    """
    Traduz texto para o idioma alvo via OllamaClient.
    Se target_language == 'English', retorna sem modificar.
    """
    if target_language == "English":
        return text

    try:
        result = agent._llm_client.generate(
            f"Translate the following text to {target_language}. "
            f"Return only the translated text, no explanations.\n\n{text}",
            temperature=0.0,
            format=None,
        )
        return result.strip()
    except Exception as e:
        logger.warning("[PA API] Translation failed: %s — returning original", e)
        return text


# Endpoints 
# ==============

@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    agent = _get_agent()
    return HealthResponse(
        status="ok",
        model=agent.config.llm.model,
    )


@app.post("/run", response_model=RunResponse)
async def run(req: RunRequest) -> RunResponse:
    """
    One-shot query. Detecta idioma, traduz para inglês,
    executa no PA, traduz resposta de volta.
    """
    agent    = _get_agent()
    language = _detect_language(req.query)

    logger.info("[PA API] /run — language=%s session=%s", language, req.session_id)

    # borda de entrada — traduz para inglês
    query_en = _translate(req.query, "English", agent) if language != "English" else req.query

    try:
        response_en = agent.run(query_en)
    except Exception as e:
        logger.exception("[PA API] agent.run failed")
        raise HTTPException(status_code=500, detail=str(e))

    # borda de saída — traduz de volta para o idioma do usuário
    response = _translate(response_en, language, agent)

    return RunResponse(
        response=response,
        session_id=req.session_id,
        language=language,
    )


@app.post("/chat", response_model=RunResponse)
async def chat(req: ChatRequest) -> RunResponse:
    """
    Turno de sessão interativa.
    Mesmo fluxo de tradução do /run.
    session_id identifica a ConversationHistory — gerado pelo cliente
    na primeira chamada e reutilizado nos turnos seguintes.
    """
    agent    = _get_agent()
    language = _detect_language(req.query)

    logger.info("[PA API] /chat — language=%s session=%s", language, req.session_id)

    query_en = _translate(req.query, "English", agent) if language != "English" else req.query

    try:
        response_en = agent.run(query_en)
    except Exception as e:
        logger.exception("[PA API] agent.run failed")
        raise HTTPException(status_code=500, detail=str(e))

    response = _translate(response_en, language, agent)

    return RunResponse(
        response=response,
        session_id=req.session_id,
        language=language,
    )