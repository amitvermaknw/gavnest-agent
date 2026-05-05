"""
gavnest-agent — FastAPI entry point.
 
Startup sequence (lifespan):
  1. Load settings
  2. Firebase app already initialized at auth/firebase.py import time
  3. (Production) swap MemorySaver for AsyncPostgresSaver
  4. Register slowapi rate limiter error handler
 
Security layers applied in order per request:
  CORS → Firebase auth Depends → slowapi rate limit → Pydantic validation → LangGraph
 
Run locally:
  uvicorn app.main:app --reload --port 8000
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.config import get_setting
from app.middleware.rate_limit import limiter
from app.api import gavvy, health, journey

settings = get_setting()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Startup / shutdown lifecycle.
 
    Production upgrade path for the checkpointer (uncomment when Cloud SQL ready):
 
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        from app.graph.graph import _build_graph
 
        async with AsyncPostgresSaver.from_conn_string(
            settings.database_url
        ) as pg_checkpointer:
            await pg_checkpointer.setup()          # creates checkpoint tables
            import app.graph.graph as g
            g.compiled_graph = g._build_graph(pg_checkpointer)
            yield
    """
    # Dev: MemorySaver is already set in graph.py — nothing extra needed.
    yield
    # Shutdown: close any open connections here

#App defined
app = FastAPI(
    title="gavnest-agent",
    description="Gavvy — home-buying AI agent service for research purpose only",
    version="0.1.0",
    lifespan=lifespan,
    # Disable auto-generated docs in production (optional)
    docs_url="/docs" if settings.langchain_tracing_v2 else None,
    redoc_url=None,
)

#Middleware: CORS
app.add_middleware(
    CORSMiddleware,
    allow_origin=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)

#Rate Limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

#Routers
app.include_router(health.router)
app.include_router(gavvy.router)
app.include_router(journey.router)

