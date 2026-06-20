"""
LLM factory — single source of truth for the model used by all agent nodes.
 
Usage in any node:
    from app.graph.llm import get_llm
    llm = get_llm()
    response = await llm.ainvoke(messages)
 
Why a factory and not a module-level singleton?
- Settings are loaded at import time — factory makes testing / mocking easier.
- @lru_cache means it's still effectively a singleton in production.
 
Streaming:
- streaming=True enables token-by-token output via astream().
- LangGraph's "messages" stream mode picks this up automatically.
"""

from functools import lru_cache
from langchain_openai import ChatOpenAI
from app.config import get_setting

@lru_cache
def get_llm() -> ChatOpenAI:
    settings = get_setting()
    return ChatOpenAI(
        model=settings.openai_model,
        api_key=settings.openai_api_key,
        streaming=True,             #Enable token stream in LangGraph message mode
        temperature=0.2             # Low temp - Factual, consistent answer for buyers
    )