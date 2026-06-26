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
- streaming=True enables real token-by-token output for the plain
  (non-structured) conversational call each agent node makes.
- with_structured_output() does NOT stream incrementally even when called via
  .astream() — LangChain buffers tool/JSON output and yields once at the end.
  So agent nodes make a separate plain call for the user-visible reply (which
  streams via get_stream_writer()) and a second structured call for
  tool_results data (silent, not streamed).
"""

import asyncio
from functools import lru_cache
from typing import Callable, TypeVar

from langchain_core.messages import BaseMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from app.config import get_setting

@lru_cache
def get_llm() -> ChatOpenAI:
    settings = get_setting()
    return ChatOpenAI(
        model=settings.openai_model,
        api_key=settings.openai_api_key,
        streaming=True,             #Enable real token-by-token output
        temperature=0.2             # Low temp - Factual, consistent answer for buyers
    )


SchemaT = TypeVar("SchemaT", bound=BaseModel)


async def stream_with_structured_output(
    llm: ChatOpenAI,
    reply_messages: list[BaseMessage],
    structured_messages: list[BaseMessage],
    schema: type[SchemaT],
    writer: Callable[[dict], None],
) -> SchemaT:
    """Get a structured response while still streaming the reply to the user.

    Runs two calls concurrently: a plain call (`reply_messages`, asking for a
    conversational reply only) whose tokens are pushed to `writer` as they
    arrive for the live chat UI, and a structured-output call
    (`structured_messages`) for the schema's other fields. `summary` on the
    result is overwritten with the streamed text so the two never diverge —
    with_structured_output() doesn't stream incrementally (LangChain buffers
    the whole tool/JSON output and yields once at the end), so it can't drive
    the live chat UI on its own.
    """
    async def _stream_text() -> str:
        chunks = []
        async for chunk in llm.astream(reply_messages):
            if chunk.content:
                writer({"type": "token", "content": chunk.content})
                chunks.append(chunk.content)
        return "".join(chunks)

    full_text, output = await asyncio.gather(
        _stream_text(),
        llm.with_structured_output(schema).ainvoke(structured_messages),
    )
    output.summary = full_text
    return output