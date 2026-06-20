"""
Firestore event logger — analytics.
 
What belongs here (product analytics):
  - agent_started       user sent a message to an agent
  - agent_completed     agent replied successfully
  - agent_error         agent failed with an error
  - tool_called         a tool (FRED, FEMA, HMDA) was invoked
  - phase_started       user entered a new phase
  - phase_completed     user marked a phase done
  - document_uploaded   user uploaded HOA doc or contract
  
Firestore collection structure:
  events/{uid}/logs/{auto_id}  →  {
      event_type, phase_id, data, created_at, session_id
  }
 
This gives per-user event history that can query for:
  - "How many users reached Phase 3?"
  - "Which phases have the most errors?"
  - "What tools are called most often?"
"""

from __future__ import annotations
import asyncio
from datetime import datetime, timezone
from typing import Any

#Firestore client - initialized lazily so local dev without
#GCP credentials doesn't crash the whole app

_db = None

def _get_db():
    global _db
    if _db is None:
        try:
            from google.cloud import firestore
            _db = firestore.AsyncClient()

        except Exception:
            #Local dev without GCP credentials - log to console only 
            _db = None
    return _db

async def log_event(
    uid: str,
    phase_id: str,
    event_type: str,
    data: dict[str, Any] | None = None,
    session_id: str | None = None
)-> None:
    """
    Write a business event to Firestore.
 
    Non-blocking — errors are swallowed so a logging failure
    never crashes the agent. Logs to console in dev mode.
 
    Args:
        uid:        Firebase user ID
        phase_id:   current phase e.g. "readiness", "mortgage"
        event_type: one of agent_started, agent_completed, agent_error,
                    tool_called, phase_started, phase_completed, document_uploaded
        data:       arbitrary dict with event-specific context
        session_id: optional, thread_id from LangGraph (uid_phase_id)
    """

    payload = {
        "event_type": event_type,
        "phase_id": phase_id,
        "session_id": session_id or f"{uid}_{phase_id}",
        "data": data or {},
        "created_at": datetime.now(timezone.utc).isoformat()
    }

    #Log to the console
    print(f"[EVENT] uid={uid} type={event_type} phase={phase_id} data={data}")

    db = _get_db()
    if db is None:
        return
    
    try:
        await db.collection("events").document(uid).collection("logs").add(payload)
    except Exception as e:
        print(f"[Event_LOGGER_ERROR] Failed to write event: {e}")

#Convenience wrappers

async def log_agent_started(uid: str, phase_id: str, message_preview: str) -> None:
    await log_event(uid, phase_id, "agent_started", {
        "message_preview": message_preview[:100]
    })

async def log_agent_completed(uid: str, phase_id: str, tools_used: list[str])-> None:
    await log_event(uid, phase_id, "agent_completed", {
        "tools_used": tools_used
    })

async def log_agent_error(uid: str, phase_id: str, error: str) -> None:
    await log_event(uid, phase_id, "agent_error",  {
        "error": error[: 500]
    })

async def log_tool_called(uid: str, phase_id: str, tool_name: str) -> None:
    await log_event(uid, phase_id, "tool_called", {
        "tool_name": tool_name
    })