"""
compute_property — Phase 3 "Search & Evaluate" calculator.

Used by POST /api/v1/journey/next-step once both property questions are
answered. Runs the FEMA flood lookup (always) and the HOA document analysis
(only if a PDF was uploaded), then makes one LLM call to produce the
structured risk breakdown — reusing PropertyOutput, which already matches
what this phase needs to persist and show the user.
"""
from __future__ import annotations

import base64
import binascii

from langchain_core.messages import HumanMessage, SystemMessage

from app.graph.llm import get_llm
from app.graph.schemas import PropertyOutput
from app.tools.fema_flood import get_flood_zone
from app.tools.hoa_analyzer import analyze_hoa_document

SYSTEM_PROMPT = """You are Gavvy, a friendly home-buying guide built by GavNest.
Your role is education only — not legal or financial advice.

Rules:
- Cite FEMA as your source for flood data.
- Summarize HOA findings clearly with risk levels.
- Use plain English. Define every term.
- For high-risk findings, explain the practical dollar impact.
- Populate every field in the response schema accurately.

You are helping with Phase 3: Evaluating a specific property.
Topics: flood risk, HOA health, special assessments, rental restrictions,
reserve funds, permit history."""


async def compute_property(answers: dict, uid: str) -> dict:
    """
    answers keys: property_address, hoa_pdf_base64 (optional — empty string
    to skip if the property has no HOA)

    Returns: {property_address, flood_zone, overall_risk, red_flags,
    recommended_steps, summary}
    """
    address = (answers.get("property_address") or "").strip()
    if not address:
        raise ValueError("property_address is required")

    hoa_pdf_base64 = answers.get("hoa_pdf_base64") or ""

    try:
        flood_data = await get_flood_zone(address)
    except RuntimeError as e:
        flood_data = {"error": str(e)}

    hoa_data = None
    if hoa_pdf_base64:
        try:
            pdf_bytes = base64.b64decode(hoa_pdf_base64, validate=True)
        except binascii.Error as e:
            raise ValueError(f"hoa_pdf_base64 is not valid base64: {e}") from e
        try:
            hoa_data = await analyze_hoa_document(
                pdf_bytes=pdf_bytes, uid=uid, property_address=address
            )
        except RuntimeError as e:
            hoa_data = {"error": str(e)}

    context = f"""
        Property address: {address}

        {_format_flood_section(flood_data, address)}

        {_format_hoa_section(hoa_data)}
        """.strip()

    structured_instruction = (
        "Populate all fields in the response schema. For flood data, use the FEMA "
        "zone information above. For HOA findings, map each finding to an "
        "HOAFinding with accurate risk levels. If no HOA document was provided, "
        "leave hoa_findings empty."
    )

    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=f"{context}\n\n{structured_instruction}"),
    ]

    output: PropertyOutput = await get_llm().with_structured_output(PropertyOutput).ainvoke(messages)

    return {
        "property_address":  address,
        "flood_zone":        flood_data.get("flood_zone"),
        "overall_risk":      output.overall_risk.value,
        "red_flags":         output.red_flags,
        "recommended_steps": output.recommended_steps,
        "summary":           output.summary,
    }


def _format_flood_section(flood_data: dict | None, address: str) -> str:
    if not flood_data:
        return "Flood data: No address provided."
    if "error" in flood_data:
        return f"Flood data: Could not retrieve — {flood_data['error']}"
    return (
        f"FEMA Flood Zone (address: {address}):\n"
        f"- Zone: {flood_data['flood_zone']}\n"
        f"- Risk: {flood_data['risk_level'].upper()}\n"
        f"- SFHA: {'YES — flood insurance likely required' if flood_data['sfha'] else 'NO'}\n"
        f"- Description: {flood_data['description']}"
    )


def _format_hoa_section(hoa_data: dict | None) -> str:
    if not hoa_data:
        return "HOA document: Not uploaded."
    if "error" in hoa_data:
        return f"HOA document: Analysis failed — {hoa_data['error']}"
    findings_text = "\n".join([
        f"  [{f['risk'].upper()}] {f['topic']}: {f['answer']}"
        for f in hoa_data.get("findings", [])
    ])
    return (
        f"HOA Document Analysis ({hoa_data['pages_analyzed']} pages):\n"
        f"Summary: {hoa_data['summary']}\n\n"
        f"Findings:\n{findings_text}"
    )
