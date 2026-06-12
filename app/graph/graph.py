"""
GavNest LangGraph graph.
 
Architecture:
  START → phase_router (conditional edge) → agent node → END
                                ↓
                 [readiness | mortgage | property | contract]
 
Checkpointer strategy:
  - Dev:  MemorySaver (in-memory, resets on restart)
  - Prod: AsyncPostgresSaver (durable, survives restarts, enables HITL resume)
 
thread_id = uid + "_" + phase_id
"""

from __future__ import annotations

import json
from typing import AsyncIterable

from langgraph.graph import END, START, StateGraph
from langgraph.checkpoint.memory import MemorySaver

from app.graph.state import GavvyState
from app.graph.router import phase_router, PHASE_TO_AGENT
from app.graph.nodes.readiness import readiness_agent
from app.graph.nodes.mortgage  import mortgage_agent
from app.graph.nodes.property  import property_agent
from app.graph.nodes.contract  import contract_agent

#Build the graph

def _build_graph(checkpointer):
    builder = StateGraph(GavvyState)

    builder.add_node("readiness_agent", readiness_agent)
    builder.add_node("mortgage_agent", mortgage_agent)
    builder.add_node("property_agent", property_agent)
    builder.add_node("contract_agent", contract_agent)

    #Deduplicate values - closing and contract both map to contract_agent
    #So below line will remove the dublicate of contract_agent
    unique_agents = list(dict.fromkeys(PHASE_TO_AGENT.values()))

    builder.add_conditional_edges(
        START,
        phase_router,
        {agent: agent for agent in unique_agents}
    )

    for agent_name in unique_agents:
        builder.add_edge(agent_name, END)
        
    return builder.compile(checkpointer=checkpointer)

#Lazy singleton
_graph_instance = None

def compiled_graph():
    global _graph_instance
    if _graph_instance is None:
        _graph_instance = _build_graph(MemorySaver())
    return _graph_instance


#Sreaming Service Function
async def stream_gavvy(
        uid: str,
        phase_id: str,
        message: str,
        user_profile: dict,
)->AsyncIterable[str]:
    """
    Core streaming function called by the FastAPI SSE route.
 
    Yields SSE-formatted strings:
        data: {"type": "thinking", "message": "..."}
        data: {"type": "token", "content": "..."}
        data: {"type": "sources", "items": [...]}
        data: {"type": "done"}
        data: {"type": "error", "message": "..."}
    """
    thread_id = f"{uid}_{phase_id}"
    config= {"configurable": {"thread_id": thread_id}}

    initial_state: GavvyState = {
        "messages": [{"role": "user", "content": message}],
        "phase_id": phase_id,
        "uid": uid,
        "user_profile": user_profile,
        "tool_results": {},
        "sources": [],
        "awaiting_human": False
    }

    try:
        graph = compiled_graph() #lazy build

        async for event in graph.astream(
            initial_state,
            config=config,
            stream_mode=["updates", "custom", "messages"]
        ):
            # When multiple stream_modes passed, LangGraph always yields
            # a tuple of (mode_name, data). Unpack defensively.
            if not isinstance(event, tuple) or len(event) != 2:
                continue
 
            event_type, event_data = event
 
            if event_type == "custom":
                if isinstance(event_data, dict):
                    yield f"data: {json.dumps(event_data)}\n\n"
 
            elif event_type == "messages":
                chunk = event_data[0] if isinstance(event_data, tuple) else event_data
                if hasattr(chunk, "content") and chunk.content:
                    yield f"data: {json.dumps({'type': 'token', 'content': chunk.content})}\n\n"
 
            elif event_type == "updates":
                if not isinstance(event_data, dict):
                    continue
                for node_name, patch in event_data.items():
                    if not isinstance(patch, dict):
                        continue
                    sources = patch.get("sources", [])
                    if sources:
                        yield f"data: {json.dumps({'type': 'sources', 'items': sources})}\n\n"

        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    except Exception as exc:
        yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"
