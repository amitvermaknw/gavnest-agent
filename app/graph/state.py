"""
Schema for everything that flow through the LangGraph graph

Design decision
- Message users add_message reducer so new message APPEND instead of replacing
- tool_results in a plain dict
phase_id drive the routes
souces accumulates citations from everytools
"""

from __future__ import annotations

from typing import Annotated, Any
from typing_extensions import TypedDict
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage

class GavvyState(TypedDict):
    #add_message reducer, new message are APPENDED not replaced
    messages: Annotated[list[BaseMessage], add_messages]

    #Routing- Which home buying phase the user is in
    # Values: "readiness" | "mortgage" | "property" | "contract" | "closing"
    phase_id: str

    #User context
    uid: str
    user_profile: dict[str, Any] #budget, creditRange, downPct, location, etc

    #Tool outputs
    tool_results: dict[str, Any]

    #Citations tools
    sources: list[dict[str, str]]

    #HITL
    awaiting_human: bool