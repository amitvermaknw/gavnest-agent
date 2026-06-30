"""
Readiness agent — Phase 1: Am I ready to buy?

Input:  ReadinessInput  (validated from user_profile)
Output: ReadinessOutput (structured LLM output via with_structured_output)
"""
from __future__ import annotations

from langchain_core.messages import AIMessage, SystemMessage, HumanMessage
from langgraph.config import get_stream_writer

from app.graph.state import GavvyState
from app.graph.llm import get_llm, stream_with_structured_output
from app.graph.schemas import ReadinessInput, ReadinessOutput
from app.tools.fred_rates import get_current_30yr_rate, get_rate_history
from app.api.firestore_writer import write_action, write_insight
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

        context = f"""
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

                Calculate the affordability breakdown and readiness score using the
                FRED rate of {current_rate["rate"]}% in all calculations.
                """.strip()

        reply_instruction = """
                Reply directly to the user in 3-5 warm, plain-English sentences using
                the numbers above. No markdown headers, bullet lists, or math notation —
                write it exactly as you'd say it out loud to a friend.
                """.strip()

        structured_instruction = "Populate all fields in the response schema accurately."

        reply_messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=f"{context}\n\n{reply_instruction}"),
        ]
        structured_messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=f"{context}\n\n{structured_instruction}"),
        ]

        # ── Structured LLM output (streamed reply + structured data concurrently)
        output: ReadinessOutput = await stream_with_structured_output(
            get_llm(), reply_messages, structured_messages, ReadinessOutput, writer
        )

        await log_agent_completed(uid, phase_id, tools_used=["fred_rates"])
        await save_the_state(state, output)
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

async def save_the_state(state: GavvyState, result: ReadinessOutput) -> None:
    actions_to_write = [
        {
            "title":       "Share your gross monthly income with Gavvy",
            "description": "Required to calculate your DTI ratio and true affordability",
            "urgency":     None
        },
        {
            "title":       "Review your estimated monthly payment",
            "description": f"Based on your profile, estimated payment is ~${result.affordability.estimated_monthly_payment}/mo",
            "urgency":     None
        }
    ]

    # Write to Firestore — frontend picks this up via real-time subscription
    for action in actions_to_write:
        await write_action(uid=state['uid'], phase=1, action=action)
    await write_insight(
        uid=state['uid'],
        phase=1,
        message=result.summary  # the human-readable summary Gavvy already generated
    )