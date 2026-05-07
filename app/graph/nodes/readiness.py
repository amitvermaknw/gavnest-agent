"""
Readiness agent — Am I ready to buy?
 
What this node does:
1. Pushes a thinking event so the UI shows progress immediately
2. Calls FRED API to get the live 30-year mortgage rate
3. Builds a prompt with the user's profile + live rate data
4. Streams the LLM response token by token back to the UI
5. Returns the full state patch (messages + sources)
 
LLM: ChatOpenAI with streaming=True
     Each token is yielded via get_stream_writer() in messages mode.

"""

from __future__ import annotations

from langchain_core.messages import AIMessage, SystemMessage, HumanMessage
from langgraph.config import get_stream_writer

from app.graph.state import GavvyState
from app.graph.llm import get_llm
from app.tools.fred_rates import get_current_30yr_rate, get_rate_history

#System prompt
SYSTEM_PROMPT = """You are Gavvy, a friendly and knowledgeable home-buying guide \
built by GavNest. Your role is to educate first-time home buyers — not to give \
financial or legal advice.
 
Rules:
- Always cite your data sources (FRED, CFPB, HUD).
- Never tell the user what they "should" do. Frame everything as education.
- Be warm, clear, and jargon-free. If you use a term, define it.
- Keep responses focused and under 300 words unless the user asks for more detail.
- End with one follow-up question to keep the conversation moving.
 
You are currently helping the user with Phase 1: Am I ready to buy?
Topics in scope: affordability, DTI ratio, true monthly cost, rent vs buy, \
credit score impact on rates, how much to save for a down payment."""

def _build_affordability_prompt(
        user_message: str,
        profile: dict,
        current_rate: dict,
        rate_history: list[dict]
)-> str:
    """
    Builds the context-rich prompt sent to the LLM.
    Keeps the LLM prompt separate from the node logic-easier to iterate
    """
    #Rate trend: compare cuirrent rate to 1 year ago
    trend_note = ""

    if len(rate_history) >= 2:
        oldest = rate_history[0]["rate"]
        newest = rate_history[-1]["rate"]
        diff = round(newest-oldest, 2)
        direction = "up" if diff > 0 else "down"
        trend_note = f"Rate are {direction} {abs(diff)}% vs one year ago."

    return f"""
    User profile:
        - Budget (max purchase price): {profile.get("budget", "not provided")}
        - Credit score range: {profile.get("creditRange", "not provided")}
        - Down payment %: {profile.get("downPct", "not provided")}%
        - Location: {profile.get("location", "not provided")}
        - Timeline: {profile.get("timeline", "not provided")}
        
        Live market data (FRED / Freddie Mac PMMS, as of {current_rate["date"]}):
        - Current 30-year fixed rate: {current_rate["rate"]}%
        - {trend_note}
        
        User's question:
        {user_message}
        
        Answer the user's question using their profile and the live rate data above.
        Cite FRED as your source for rate data.
    """.strip()

async def readiness_agent(state: GavvyState)-> dict:
    """
    LangGraph calls this with the current state.
    Returns a dict — LangGraph merges it into state via the reducers.
    """

    writer = get_stream_writer()
    llm = get_llm()

    #Step 1: Gavvy is thinking
    writer({"type": "thinking", "message": "Analyzing your readiness profile..."})

    #Step 2: Fetch live FRED data
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