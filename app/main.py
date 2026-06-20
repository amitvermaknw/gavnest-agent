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
docker run -d --name gavnest-pg -e POSTGRES_PASSWORD=postgres \
    -e POSTGRES_DB=gavnest -p 5432:5432 postgres:16
  uvicorn app.main:app --reload --port 8000
"""

from __future__ import annotations

from contextlib import asynccontextmanager
import warnings
 
# Suppress harmless LangChain + Pydantic serialization warnings
warnings.filterwarnings("ignore", category=UserWarning, module="pydantic.main")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.config import get_setting
from app.middleware.rate_limit import limiter
from app.api import gavvy, health, journey
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from app.graph.graph import _build_graph
import app.graph.graph as g

settings = get_setting()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Startup: initialize AsyncPostgresSaver checkpointer.
    This replaces the MemorySaver singleton in graph.py with a
    durable Postgres-backed one so state survives restarts.
    """
    try:
        
        db_url = settings.NEON_POSTGRESQL_DB.replace("?sslmode=require", "")
        conn_kwargs = {"ssl": "require"} if "neon.tech" in settings.NEON_POSTGRESQL_DB else {}
 
        async with AsyncPostgresSaver.from_conn_string(
            db_url,
            **conn_kwargs,
        ) as pg_checkpointer:
            await pg_checkpointer.setup()          # creates checkpoint tables if not exist
            g._graph_instance = g._build_graph(pg_checkpointer)
            print(f"[STARTUP] AsyncPostgresSaver initialized — durable checkpointing active")
            yield

    except Exception as e:
        # Fallback to MemorySaver if Postgres is unavailable
        # Useful when running without Docker locally
        print(f"[STARTUP] Postgres unavailable ({e}) — falling back to MemorySaver")
        yield

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
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
    allow_origin_regex=r"null" if settings.dev_mode else None,
)

#Rate Limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

#Routers
app.include_router(health.router)
app.include_router(gavvy.router)
app.include_router(journey.router)

# Access at: http://localhost:8000/test/test.html
import os
_test_dir = "test" if os.path.exists("test") else "app/test"
if settings.dev_mode and os.path.exists(_test_dir):
    app.mount("/test", StaticFiles(directory=_test_dir), name="static")