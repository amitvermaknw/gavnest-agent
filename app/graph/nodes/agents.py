from __future__ import annotations

from langchain_core.messages import AIMessage
from langgraph.config import get_stream_writer
from app.graph.state import GavvyState


async def mortgage_agent(state: GavvyState):
    writer = get_stream_writer()
    writer({"type": "thinking", "message": "Fetching rate range for your credit tier..."})

    return {
        "messages": [AIMessage(content="[Mortgage agent ]")],
        "tool_results": {},
        "sources": [],
        "awaiting_human": False,
    } 

async def property_agent(state: GavvyState) -> dict:
    """HOA doc analysis + FEMA flood check. Uses FEMA + HOA tools."""
    writer = get_stream_writer()
    writer({"type": "thinking", "message": "Checking flood zone and HOA documents..."})
 
    return {
        "messages": [AIMessage(content="[Property agent ]")],
        "tool_results": {},
        "sources": [],
        "awaiting_human": False,
    }
 
 
async def contract_agent(state: GavvyState) -> dict:
    """contract plain-English decode + closing costs. Uses PDF RAG tool."""
    writer = get_stream_writer()
    writer({"type": "thinking", "message": "Reading your contract clauses..."})
 
    return {
        "messages": [AIMessage(content="[Contract agent ]")],
        "tool_results": {},
        "sources": [],
        "awaiting_human": False,
    }