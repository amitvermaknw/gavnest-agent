"""
Mortgage agent — Phase 2: Getting Pre-Approved.

Input:  MortgageInput  (validated from user_profile)
Output: MortgageOutput (structured LLM output via with_structured_output)
"""
from __future__ import annotations

from langchain_core.messages import AIMessage, SystemMessage, HumanMessage
from langgraph.config import get_stream_writer

from app.graph.state import GavvyState
from app.graph.llm import get_llm
from app.graph.schemas import MortgageInput, MortgageOutput
from app.tools.fred_rates import get_current_30yr_rate
from app.tools.hmda_rates import get_all_tiers, get_cost_difference
from app.services.event_logger import (
    log_agent_started,
    log_agent_completed,
    log_agent_error,
    log_tool_called,
)


SYSTEM_PROMPT = """You are Gavvy, a friendly home-buying guide built by GavNest.
Your role is education only — never financial advice.

Rules:
- Cite FRED and FHFA National Mortgage Database as data sources.
- Use plain English. Define every term you use.
- Show numbers concretely: monthly payments, total 30-year costs.
- Never tell the user what to do. Show them the data and let them decide.
- Populate every field in the response schema accurately.

You are helping with Phase 2: Getting Pre-Approved.
Topics: interest rates by credit tier, loan types (conventional, FHA, VA, USDA),
what affects your rate, how to read a Loan Estimate, DTI limits, points and buydowns."""


async def mortgage_agent(state: GavvyState) -> dict:
    writer = get_stream_writer()
    uid = state.get("uid", "unknown")
    phase_id = state.get("phase_id", "mortgage")
    user_message = _extract_last_user_message(state)

    await log_agent_started(uid, phase_id, user_message)
    writer({"type": "thinking", "message": "Looking up mortgage rate data..."})

    try:
        # ── Validate input 
        try:
            inp = MortgageInput.from_profile(state.get("user_profile", {}))
        except ValueError as e:
            raise RuntimeError(f"Invalid profile data: {e}") from e

        # ── Fetch FRED rate 
        await log_tool_called(uid, phase_id, "fred_rates")
        writer({"type": "thinking", "message": "Fetching current mortgage rates from FRED..."})
        current_rate = await get_current_30yr_rate()

        # ── Read tier data from Firestore 
        await log_tool_called(uid, phase_id, "hmda_rates")
        writer({"type": "thinking", "message": "Calculating rate ranges by credit tier..."})

        all_tiers = await get_all_tiers(current_rate["rate"])
        user_tier = all_tiers.get(inp.credit_range.value, all_tiers["Good"])
        excellent_tier = all_tiers["Excellent"]

        loan_amount = inp.budget * (1 - inp.down_pct / 100)
        cost_diff = get_cost_difference(
            excellent_rate=excellent_tier["rate_mid"],
            user_rate=user_tier["rate_mid"],
            loan_amount=loan_amount,
        )

        # ── Build prompt 
        writer({"type": "thinking", "message": "Gavvy is thinking..."})

        tier_table = "\n".join([
            f"  {t['tier']:10} ({t['score_range']}): "
            f"{t['rate_low']}% - {t['rate_high']}%  "
            f"→ ${t['monthly_payment_300k']:,}/mo on $300k"
            for t in all_tiers.values()
        ])

        rate_premium = round(user_tier["rate_mid"] - excellent_tier["rate_mid"], 2)

        prompt = f"""
            User profile:
            - Budget: ${inp.budget:,.0f}
            - Loan amount: ${loan_amount:,.0f}
            - Credit tier: {inp.credit_range.value}
            - Down payment: {inp.down_pct}%
            - Location: {inp.location or "not provided"}
            - Preferred loan type: {inp.loan_type.value}

            Live rate data (FRED, as of {current_rate["date"]}):
            - 30-year benchmark: {current_rate["rate"]}%

            Rate ranges by credit tier (FHFA NMDB, adjusted to current FRED):
            {tier_table}

            User's credit tier ({inp.credit_range.value}):
            - Rate range:          {user_tier["rate_low"]}% - {user_tier["rate_high"]}%
            - vs Excellent:        +{rate_premium}%
            - Monthly extra cost:  ${cost_diff["monthly_difference"]}/mo
            - 30yr total extra:    ${cost_diff["total_30yr_difference"]:,.0f}

            User's question:
            {user_message}

            Populate the response schema with accurate numbers from the data above.
            Explain the tier comparison and 30-year cost impact clearly.
            Provide concrete pre-approval steps.
            """.strip()

        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ]

        # ── Structured LLM output 
        structured_llm = get_llm().with_structured_output(MortgageOutput)
        output: MortgageOutput = await structured_llm.ainvoke(messages)

        await log_agent_completed(uid, phase_id, tools_used=["fred_rates", "hmda_rates"])

        return {
            "messages": [AIMessage(content=output.summary)],
            "tool_results": output.model_dump(),
            "sources": [
                {
                    "source":  "FRED / Freddie Mac PMMS",
                    "url":     "https://fred.stlouisfed.org/series/MORTGAGE30US",
                    "snippet": f"30-year fixed: {current_rate['rate']}% as of {current_rate['date']}",
                },
                {
                    "source":  "FHFA National Mortgage Database",
                    "url":     "https://www.fhfa.gov/data/national-mortgage-database",
                    "snippet": (
                        f"{inp.credit_range.value} credit tier: "
                        f"{user_tier['rate_low']}% - {user_tier['rate_high']}%"
                    ),
                },
            ],
            "awaiting_human": False,
        }

    except Exception as e:
        await log_agent_error(uid, phase_id, str(e))
        raise


def _extract_last_user_message(state: GavvyState) -> str:
    messages = state.get("messages", [])
    if not messages:
        return "Tell me about mortgage rates and getting pre-approved."
    last = messages[-1]
    if hasattr(last, "content"):
        return last.content
    if isinstance(last, dict):
        return last.get("content", "")
    return "Tell me about mortgage rates and getting pre-approved."