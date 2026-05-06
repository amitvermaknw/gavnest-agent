"""
Readiness agent - Phase 1 - Am I ready to buy?

Responsibilities:
- Affordability score
- DTI calculation
- Rent vs buy analysis
- Pulls live 30 year rate from FRED tool
"""

from __future__ import annotations

from langchain_core.messages import AIMessage
from langgraph.config import get_stream_writer

from app.graph.state import GavvyState
from app.graph.llm import get_llm

async def readiness_agent(state: GavvyState)-> dict:
    """
    Returns a state patch - Langgrap merges it via the add_message reducer
    """

    writer = get_stream_writer()

    #Gavvy is thinking
    writer({"type": "thinking", "message": "Analyzing your readiness profile..."})

     # ── Placeholder: Weekend 2 will call FRED tool here via Send API ─────────
    # from app.tools.fred_rates import get_current_30yr_rate
    # rate = await get_current_30yr_rate()

    writer({"type": "thinking", "message": "Fetching current mortgage rates from FRED..."})

    #stub response - replace with LLM
    profile = state.get("user_profile", {})
    budget = profile.get("budget", "unknow")
    credit = profile.get("creditRange", "unknow")

    response = (
        f"Based on your profile (budget: {budget}, credit:{credit}),"
        "here's your readiness assessment. [FRED rate data will come here]"
        "The key question is where your ru monthly payment-inclouding taxes,"
        "insurance, PML and HOA-fits within 28 of your gross monthly income "
    )

    writer({"type": "done", "message": "Analysis complete"})

    return {
        "message": [AIMessage(content=response)],
        "tool_results": {"readiness_stub": True},
        "sources": [],
        "awaiting_human": False
    }