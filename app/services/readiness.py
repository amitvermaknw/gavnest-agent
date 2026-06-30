"""
compute_readiness — Phase 1 "Am I ready to buy?" calculator.

Used by POST /api/v1/journey/next-step once all 4 readiness questions are
answered. All math (DTI, true budget, estimated payment) is plain Python —
auditable and reproducible. The only LLM call is for the verdict + the
natural-language summary, so Gavvy's voice stays warm without the numbers
ever being something the model could get wrong.
"""
from __future__ import annotations

from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.graph.llm import get_llm
from app.tools.fred_rates import get_current_30yr_rate

# Conventional underwriting guidelines (28/36 rule + QM back-end ceiling).
FRONT_END_DTI_MAX = 0.28   # housing payment shouldn't exceed 28% of gross income
BACK_END_DTI_MAX = 0.36    # housing + other debts shouldn't exceed 36% of gross income
BACK_END_DTI_CEILING = 0.43  # beyond this, most loan programs won't qualify the buyer
PI_SHARE_OF_PAYMENT = 0.78   # rough P&I share of PITI; rest is taxes/insurance
LOAN_TERM_MONTHS = 360       # 30-year fixed
FALLBACK_RATE_PCT = 7.0      # used only if FRED is unreachable

SYSTEM_PROMPT = """You are Gavvy, a friendly home-buying guide built by GavNest.
Your role is education only — never financial advice.

You are given a buyer's affordability numbers, already calculated in Python.
Do not recompute, second-guess, or contradict them — your job is to decide a
verdict and explain the numbers warmly.

Conventional guideline for the verdict:
- back-end debt-to-income at or below 36% -> "ready"
- back-end debt-to-income between 36% and 43% -> "almost"
- back-end debt-to-income above 43% -> "not_yet"

Rules:
- Be warm, clear, and jargon-free. Never lecture.
- Reference the actual numbers you were given.
- Frame everything as education, never as instruction or financial advice.
- Write the summary as 2-4 sentences, like you're talking to a friend."""


class ReadinessVerdict(BaseModel):
    verdict: Literal["ready", "almost", "not_yet"] = Field(..., description="Overall readiness verdict")
    summary: str = Field(..., min_length=10, description="Warm, plain-English summary for the user")


def _format_budget(value: float) -> str:
    """420000 -> '$420k', 1250000 -> '$1.3M'."""
    if value >= 1_000_000:
        return f"${value / 1_000_000:.1f}M"
    return f"${round(value / 1000)}k"


async def compute_readiness(answers: dict) -> dict:
    """
    answers keys: gross_monthly_income, monthly_debts, liquid_savings, employment_status

    Returns: {true_budget, dti, estimated_payment, verdict, summary}
    """
    income = float(answers.get("gross_monthly_income") or 0)
    debts = float(answers.get("monthly_debts") or 0)
    savings = float(answers.get("liquid_savings") or 0)
    employment_status = answers.get("employment_status") or "not provided"

    if income <= 0:
        raise ValueError("gross_monthly_income must be greater than 0")

    max_housing_payment = max(0.0, min(income * FRONT_END_DTI_MAX, income * BACK_END_DTI_MAX - debts))
    dti_pct = round((debts + max_housing_payment) / income * 100, 1)

    try:
        rate_info = await get_current_30yr_rate()
        annual_rate_pct = rate_info["rate"]
    except RuntimeError:
        annual_rate_pct = FALLBACK_RATE_PCT

    monthly_rate = annual_rate_pct / 100 / 12
    pi_payment = max_housing_payment * PI_SHARE_OF_PAYMENT

    if monthly_rate > 0:
        loan_amount = pi_payment * (1 - (1 + monthly_rate) ** -LOAN_TERM_MONTHS) / monthly_rate
    else:
        loan_amount = pi_payment * LOAN_TERM_MONTHS

    true_budget = loan_amount + savings
    estimated_payment = round(max_housing_payment)

    verdict_messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(
            content=(
                f"Buyer's computed numbers:\n"
                f"- True affordable budget: ${true_budget:,.0f}\n"
                f"- Estimated monthly payment (PITI): ${estimated_payment:,.0f}\n"
                f"- Back-end debt-to-income ratio: {dti_pct}%\n"
                f"- Gross monthly income: ${income:,.0f}\n"
                f"- Existing monthly debts: ${debts:,.0f}\n"
                f"- Liquid savings available: ${savings:,.0f}\n"
                f"- Employment status: {employment_status}\n\n"
                f"Decide the verdict and write the summary."
            )
        ),
    ]

    result: ReadinessVerdict = await get_llm().with_structured_output(ReadinessVerdict).ainvoke(verdict_messages)

    return {
        "true_budget": _format_budget(true_budget),
        "dti": f"{round(dti_pct)}%",
        "estimated_payment": estimated_payment,
        "verdict": result.verdict,
        "summary": result.summary,
    }
