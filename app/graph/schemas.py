"""
Agent input/output schemas — Pydantic models for all agents.

Two purposes:
1. Input validation  — validate state fields before calling the LLM
                       raises ValueError early with a clear message
2. Structured output — passed to llm.with_structured_output(Schema)
                       LangChain uses function calling to force the LLM
                       to return valid structured data, not free text

This eliminates hallucination at the schema level — if the LLM tries
to return a field that doesn't exist or the wrong type, it gets rejected
and retried automatically by LangChain.

Usage in an agent:
    from app.graph.schemas import MortgageInput, MortgageOutput

    # Validate input
    inp = MortgageInput(**state.get("user_profile", {}))

    # Structured LLM output
    structured_llm = llm.with_structured_output(MortgageOutput)
    output: MortgageOutput = await structured_llm.ainvoke(messages)
"""
from __future__ import annotations

import re
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field, field_validator


# ══════════════════════════════════════════════════════════════════════════════
# SHARED HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def parse_money(value) -> float:
    """Parse a money value from the client, which may be a number or a string
    like '$300,000', '300k', or a range like '$250k-$350k'.

    Ranges resolve to the midpoint of their bounds.
    """
    if value is None or value == "":
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)

    bounds = []
    for part in re.split(r"-|-|\bto\b", str(value).lower()):
        part = part.strip().replace("$", "").replace(",", "")
        if not part:
            continue
        multiplier = 1
        if part.endswith("k"):
            multiplier, part = 1_000, part[:-1]
        elif part.endswith("m"):
            multiplier, part = 1_000_000, part[:-1]
        bounds.append(float(part) * multiplier)

    if not bounds:
        raise ValueError(f"Could not parse money value: {value!r}")
    return sum(bounds) / len(bounds)


# ══════════════════════════════════════════════════════════════════════════════
# SHARED ENUMS
# ══════════════════════════════════════════════════════════════════════════════

class CreditTier(str, Enum):
    excellent = "Excellent"
    good      = "Good"
    fair      = "Fair"
    poor      = "Poor"


class RiskLevel(str, Enum):
    high          = "high"
    medium        = "medium"
    low           = "low"
    not_found     = "not_found"
    undetermined  = "undetermined"


class LoanType(str, Enum):
    conventional = "Conventional"
    fha          = "FHA"
    va           = "VA"
    usda         = "USDA"


# ══════════════════════════════════════════════════════════════════════════════
# READINESS AGENT
# ══════════════════════════════════════════════════════════════════════════════

class ReadinessInput(BaseModel):
    """Validated input for the readiness agent from user_profile."""
    budget:      float  = Field(...,  gt=0,         description="Max purchase price in USD")
    credit_range: CreditTier = Field(CreditTier.good, description="Credit score tier")
    down_pct:    float  = Field(20.0, ge=0, le=100, description="Down payment percentage")
    location:    str    = Field("",                 description="City and state")
    timeline:    str    = Field("",                 description="Buying timeline e.g. 6 months")
    gross_monthly_income: Optional[float] = Field(None, gt=0, description="Gross monthly income in USD")

    @field_validator("budget")
    @classmethod
    def budget_reasonable(cls, v):
        if v < 50_000:
            raise ValueError("Budget seems too low — must be at least $50,000")
        if v > 10_000_000:
            raise ValueError("Budget exceeds $10M — please verify")
        return v

    @classmethod
    def from_profile(cls, profile: dict) -> "ReadinessInput":
        """Build from the user_profile dict in GavvyState."""
        return cls(
            budget=parse_money(profile.get("budget", 0)),
            credit_range=CreditTier(profile.get("creditRange", "Good")),
            down_pct=float(profile.get("downPct", 20)),
            location=profile.get("location", ""),
            timeline=profile.get("timeline", ""),
            gross_monthly_income=parse_money(profile.get("grossMonthlyIncome")) or None,
        )


class AffordabilityBreakdown(BaseModel):
    estimated_monthly_payment: float = Field(..., description="Estimated total monthly payment in USD")
    principal_and_interest:    float = Field(..., description="P&I portion of monthly payment")
    estimated_taxes_insurance: float = Field(..., description="Estimated monthly taxes + insurance")
    dti_ratio:                 Optional[float] = Field(None, description="Debt-to-income ratio as percentage")
    max_recommended_budget:    float = Field(..., description="True recommended max budget based on income")
    down_payment_amount:       float = Field(..., description="Down payment amount in USD")
    loan_amount:               float = Field(..., description="Loan amount after down payment")


class ReadinessOutput(BaseModel):
    """Structured LLM output for Phase 1 readiness assessment."""
    affordability:     AffordabilityBreakdown
    is_ready:          bool  = Field(..., description="Whether user appears financially ready to buy")
    readiness_score:   int   = Field(..., ge=0, le=100, description="Readiness score 0-100")
    key_strengths:     list[str] = Field(..., min_length=1, description="Positive readiness factors")
    key_concerns:      list[str] = Field(default_factory=list, description="Areas needing attention")
    recommended_steps: list[str] = Field(..., min_length=1, description="Concrete next steps for the user")
    summary:           str   = Field(..., min_length=10, description="Plain-English summary for the user")
    current_rate:      float = Field(..., description="Current 30yr rate from FRED used in calculation")
    rate_date:         str   = Field(..., description="Date of the FRED rate observation")


# ══════════════════════════════════════════════════════════════════════════════
# MORTGAGE AGENT 
# ══════════════════════════════════════════════════════════════════════════════

class MortgageInput(BaseModel):
    """Validated input for the mortgage agent."""
    budget:       float      = Field(...,  gt=0,         description="Max purchase price in USD")
    credit_range: CreditTier = Field(CreditTier.good,    description="Credit score tier")
    down_pct:     float      = Field(20.0, ge=0, le=100, description="Down payment percentage")
    location:     str        = Field("",                 description="City and state")
    loan_type:    LoanType   = Field(LoanType.conventional, description="Preferred loan type")

    @classmethod
    def from_profile(cls, profile: dict) -> "MortgageInput":
        return cls(
            budget=parse_money(profile.get("budget", 0)),
            credit_range=CreditTier(profile.get("creditRange", "Good")),
            down_pct=float(profile.get("downPct", 20)),
            location=profile.get("location", ""),
            loan_type=LoanType(profile.get("loanType", "Conventional")),
        )


class TierRateData(BaseModel):
    tier:                 CreditTier
    score_range:          str   = Field(..., description="e.g. 720-759")
    rate_low:             float = Field(..., description="Low end of rate range")
    rate_high:            float = Field(..., description="High end of rate range")
    rate_mid:             float = Field(..., description="Midpoint rate estimate")
    monthly_payment_300k: int   = Field(..., description="Monthly payment on $300k loan")


class MortgageOutput(BaseModel):
    """Structured LLM output for Phase 2 mortgage education."""
    user_rate_low:   float = Field(..., description="Low end rate estimate for user's credit tier")
    user_rate_high:  float = Field(..., description="High end rate estimate for user's credit tier")
    user_monthly_payment: int = Field(..., description="Estimated monthly payment for user's loan amount")
    monthly_vs_excellent: int = Field(..., description="Extra monthly cost vs Excellent credit tier")
    total_30yr_extra:     float = Field(..., description="Total extra cost over 30 years vs Excellent")
    loan_amount:          float = Field(..., description="Loan amount after down payment")
    key_points:           list[str] = Field(..., min_length=2, description="Key education points for the user")
    loan_type_explanation: str  = Field(..., description="Plain-English explanation of recommended loan type")
    next_steps:           list[str] = Field(..., min_length=1, description="Concrete pre-approval steps")
    summary:              str   = Field(..., min_length=10, description="Plain-English summary")
    current_rate:         float = Field(..., description="Current FRED 30yr benchmark rate")
    rate_date:            str   = Field(..., description="Date of FRED rate observation")


# ══════════════════════════════════════════════════════════════════════════════
# PROPERTY AGENT
# ══════════════════════════════════════════════════════════════════════════════

class PropertyInput(BaseModel):
    """Validated input for the property agent."""
    property_address: str   = Field("", description="Full US property address")
    budget:           float = Field(0.0, ge=0, description="Purchase budget in USD")
    location:         str   = Field("",        description="General location")

    @classmethod
    def from_profile(cls, profile: dict) -> "PropertyInput":
        return cls(
            property_address=str(profile.get("property_address") or ""),
            budget=parse_money(profile.get("budget")),
            location=str(profile.get("location") or ""),
        )


class FloodFinding(BaseModel):
    flood_zone:          str       = Field(..., description="FEMA flood zone code e.g. AE, X")
    risk_level:          RiskLevel = Field(..., description="Overall flood risk level")
    sfha:                bool      = Field(..., description="In Special Flood Hazard Area")
    insurance_required:  bool      = Field(..., description="Flood insurance federally required")
    plain_english:       str       = Field(..., description="Plain-English explanation for buyer")
    monthly_cost_estimate: Optional[float] = Field(None, description="Estimated monthly flood insurance cost")


class HOAFinding(BaseModel):
    topic:   str       = Field(..., description="Finding topic e.g. Special Assessments")
    answer:  str       = Field(..., description="What the document says")
    risk:    RiskLevel = Field(..., description="Risk level of this finding")
    impact:  str       = Field(..., description="Plain-English impact on the buyer")


class PropertyOutput(BaseModel):
    """Structured LLM output for Phase 3 property evaluation."""
    flood_finding:    Optional[FloodFinding]  = Field(None, description="Flood zone analysis")
    hoa_findings:     list[HOAFinding]        = Field(default_factory=list, description="HOA document findings")
    overall_risk:     RiskLevel               = Field(..., description="Overall property risk level")
    red_flags:        list[str]               = Field(default_factory=list, description="High priority concerns")
    positive_signals: list[str]               = Field(default_factory=list, description="Positive property attributes")
    recommended_steps: list[str]              = Field(..., min_length=1, description="Next steps for the buyer")
    summary:          str                     = Field(..., min_length=10, description="Plain-English property summary")


# ══════════════════════════════════════════════════════════════════════════════
# CONTRACT AGENT
# ══════════════════════════════════════════════════════════════════════════════

class ContractInput(BaseModel):
    """Validated input for the contract agent."""
    property_address: str   = Field("", description="Property address")
    budget:           float = Field(0.0, ge=0, description="Purchase budget")
    location:         str   = Field("", description="State — needed for closing cost calc")
    offer_price:      Optional[float] = Field(None, gt=0, description="Offer price if known")

    @classmethod
    def from_profile(cls, profile: dict) -> "ContractInput":
        return cls(
            property_address=profile.get("property_address", ""),
            budget=parse_money(profile.get("budget", 0)),
            location=profile.get("location", ""),
            offer_price=parse_money(profile.get("offerPrice")) or None,
        )


class ClauseFinding(BaseModel):
    clause_name:  str       = Field(..., description="Name of the contract clause")
    plain_english: str      = Field(..., description="Plain-English explanation")
    risk:         RiskLevel = Field(..., description="Risk level of this clause")
    negotiable:   bool      = Field(..., description="Whether this clause is typically negotiable")
    red_flag:     bool      = Field(..., description="Whether this is a red flag for the buyer")


class ClosingCostBreakdown(BaseModel):
    loan_origination:     float = Field(0.0, description="Lender origination fee")
    title_insurance:      float = Field(0.0, description="Title insurance")
    escrow_fees:          float = Field(0.0, description="Escrow/settlement fees")
    recording_fees:       float = Field(0.0, description="Government recording fees")
    prepaid_interest:     float = Field(0.0, description="Prepaid mortgage interest")
    homeowners_insurance: float = Field(0.0, description="First year homeowners insurance")
    property_tax_escrow:  float = Field(0.0, description="Property tax escrow deposit")
    total:                float = Field(0.0, description="Total closing costs")
    pct_of_purchase:      float = Field(0.0, description="Closing costs as % of purchase price")


class ContractOutput(BaseModel):
    """Structured LLM output for Phases 4-5 contract analysis."""
    clause_findings:   list[ClauseFinding]  = Field(default_factory=list, description="Contract clause analysis")
    closing_costs:     Optional[ClosingCostBreakdown] = Field(None, description="Closing cost breakdown")
    red_flags:         list[str]            = Field(default_factory=list, description="Contract red flags")
    contingencies:     list[str]            = Field(default_factory=list, description="Active contingencies found")
    waived_protections: list[str]           = Field(default_factory=list, description="Any waived buyer protections")
    negotiation_tips:  list[str]            = Field(default_factory=list, description="Negotiation opportunities")
    recommended_steps: list[str]            = Field(..., min_length=1, description="Next steps")
    summary:           str                  = Field(..., min_length=10, description="Plain-English contract summary")