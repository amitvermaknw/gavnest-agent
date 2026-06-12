"""
Readiness agent — Phase 1: Am I ready to buy?

Input:  ReadinessInput  (validated from user_profile)
Output: ReadinessOutput (structured LLM output via with_structured_output)
"""
from __future__ import annotations

from langchain_core.messages import AIMessage, SystemMessage, HumanMessage
from langgraph.config import get_stream_writer

from app.graph.state import GavvyState
from app.graph.llm import get_llm
from app.graph.schemas import ReadinessInput, ReadinessOutput
from app.tools.fred_rates import get_current_30yr_rate, get_rate_history
from app.services.event_logger import (
    log_agent_started,
    log_agent_completed,
    log_agent_error,
    log_tool_called,
)


SYSTEM_PROMPT = """You are Gavvy, a friendly home-buying guide built by GavNest.
Your role is education only — never financial advice.

Rules:
- Cite FRED as your data source for mortgage rates.
- Be warm, clear, and jargon-free. Define every term you use.
- Show concrete numbers: monthly payments, DTI ratios, down payment amounts.
- Never tell the user what to do. Frame everything as education.
- Populate every field in the response schema accurately.

You are helping with Phase 1: Am I ready to buy?
Topics: affordability, DTI ratio, true monthly cost, rent vs buy,
credit score impact, how much to save for a down payment."""


async def readiness_agent(state: GavvyState) -> dict:
    writer = get_stream_writer()
    uid = state.get("uid", "unknown")
    phase_id = state.get("phase_id", "readiness")
    user_message = _extract_last_user_message(state)

    await log_agent_started(uid, phase_id, user_message)
    writer({"type": "thinking", "message": "Analyzing your readiness profile..."})

    try:
        # ── Validate input 
        try:
            inp = ReadinessInput.from_profile(state.get("user_profile", {}))
        except ValueError as e:
            raise RuntimeError(f"Invalid profile data: {e}") from e

        # ── Fetch FRED data 
        await log_tool_called(uid, phase_id, "fred_rates")
        writer({"type": "thinking", "message": "Fetching live mortgage rates from FRED..."})

        import asyncio
        current_rate, rate_history = await asyncio.gather(
            get_current_30yr_rate(),
            get_rate_history(limit=52),
        )

        # ── Rate trend──
        trend_note = ""
        if len(rate_history) >= 2:
            diff = round(rate_history[-1]["rate"] - rate_history[0]["rate"], 2)
            direction = "up" if diff > 0 else "down"
            trend_note = f"Rates are {direction} {abs(diff)}% vs one year ago."

        # ── Build prompt
        writer({"type": "thinking", "message": "Gavvy is thinking..."})

        loan_amount = inp.budget * (1 - inp.down_pct / 100)

        prompt = f"""
                User profile:
                - Budget (max purchase price): ${inp.budget:,.0f}
                - Loan amount after down payment: ${loan_amount:,.0f}
                - Down payment: {inp.down_pct}% (${inp.budget * inp.down_pct / 100:,.0f})
                - Credit score range: {inp.credit_range.value}
                - Location: {inp.location or "not provided"}
                - Timeline: {inp.timeline or "not provided"}
                - Gross monthly income: {"${:,.0f}".format(inp.gross_monthly_income) if inp.gross_monthly_income else "not provided"}

                Live market data (FRED / Freddie Mac PMMS, as of {current_rate["date"]}):
                - Current 30-year fixed rate: {current_rate["rate"]}%
                - {trend_note}

                User's question:
                {user_message}

                Calculate the affordability breakdown, readiness score, and provide
                concrete next steps. Use the FRED rate of {current_rate["rate"]}% in all calculations.
                Populate all fields in the response schema.
                """.strip()

        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ]

        # ── Structured LLM output 
        structured_llm = get_llm().with_structured_output(ReadinessOutput)
        output: ReadinessOutput = await structured_llm.ainvoke(messages)

        await log_agent_completed(uid, phase_id, tools_used=["fred_rates"])

        return {
            "messages": [AIMessage(content=output.summary)],
            "tool_results": output.model_dump(),
            "sources": [
                {
                    "source":  "FRED / Freddie Mac PMMS",
                    "url":     "https://fred.stlouisfed.org/series/MORTGAGE30US",
                    "snippet": f"30-year fixed: {current_rate['rate']}% as of {current_rate['date']}",
                }
            ],
            "awaiting_human": False,
        }

    except Exception as e:
        await log_agent_error(uid, phase_id, str(e))
        raise


def _extract_last_user_message(state: GavvyState) -> str:
    messages = state.get("messages", [])
    if not messages:
        return "Tell me about my home-buying readiness."
    last = messages[-1]
    if hasattr(last, "content"):
        return last.content
    if isinstance(last, dict):
        return last.get("content", "")
    return "Tell me about my home-buying readiness."