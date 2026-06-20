"""
POST /api/gavvy — SSE streaming endpoint.
 
Flow:
  1. Firebase auth dependency verifies the Bearer token → uid
  2. Rate limiter checks 20 req/min per uid
  3. Pydantic validates the request body → ChatRequest
  4. uid is stored on request.state (used by rate limiter key fn)
  5. stream_gavvy() runs the LangGraph graph and yields SSE events
  6. StreamingResponse pushes events to Next.js as they arrive
 
SSE event types the client should handle:
  { "type": "thinking", "message": "Fetching FRED rates..." }
  { "type": "token",    "content": "The current 30-year..." }
  { "type": "sources",  "items": [{"source": "FRED", "url": "..."}] }
  { "type": "done" }
  { "type": "error",    "message": "..." }
 
headers:
  X-Accel-Buffering: no  — disables nginx/Cloud Run proxy buffering.
  Without this, the proxy batches chunks and SSE stops feeling real-time.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.auth import FirebaseUser, get_current_user
from app.graph import stream_gavvy
from app.middleware.rate_limit import limiter

router = APIRouter(prefix="/api/v1")

#Schema
class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    phase_id: str = Field(
        default="readiness",
        pattern="^(readiness|mortgage|property|contract|closing)$"
    )

    user_profile: dict = Field(default_factory=dict)

#route 
@router.post("/gavvy")
async def gavvy(request: Request, body: ChatRequest, user: FirebaseUser=Depends(get_current_user)):
    """
    Main Gavvy chat endpoint.
    Streams SSE events back to Next.js as the LangGraph graph executes.
    """

    #Store uid on request.state s the rate limiter key fn can read it
    request.state.uid = user.uid

    return StreamingResponse(
        stream_gavvy(
            uid=user.uid,
            phase_id=body.phase_id,
            message=body.message,
            user_profile=body.user_profile
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )
