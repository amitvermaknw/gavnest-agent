"""
Property agent — Phase 3: Search & Evaluate.

Input:  PropertyInput  (validated from user_profile)
Output: PropertyOutput (structured LLM output via with_structured_output)
"""
from __future__ import annotations

from langchain_core.messages import AIMessage, SystemMessage, HumanMessage
from langgraph.config import get_stream_writer

from app.graph.state import GavvyState
from app.graph.llm import get_llm
from app.graph.schemas import PropertyInput, PropertyOutput
from app.tools.fema_flood import get_flood_zone
from app.tools.hoa_analyzer import analyze_hoa_document
from app.services.event_logger import (
    log_agent_started,
    log_agent_completed,
    log_agent_error,
    log_tool_called,
)


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


async def property_agent(state: GavvyState) -> dict:
    writer = get_stream_writer()
    llm = get_llm()
    uid = state.get("uid", "unknown")
    phase_id = state.get("phase_id", "property")
    user_message = _extract_last_user_message(state)

    await log_agent_started(uid, phase_id, user_message)
    writer({"type": "thinking", "message": "Researching this property..."})

    try:
        # ── Validate input 
        try:
            inp = PropertyInput.from_profile(state.get("user_profile", {}))
        except ValueError as e:
            raise RuntimeError(f"Invalid profile data: {e}") from e

        hoa_pdf_bytes = state.get("tool_results", {}).get("hoa_pdf_bytes")
        flood_data    = None
        hoa_data      = None
        tools_used    = []

        # ── FEMA flood zone check 
        if inp.property_address:
            await log_tool_called(uid, phase_id, "fema_flood")
            writer({"type": "thinking", "message": f"Checking flood zone for {inp.property_address}..."})
            try:
                flood_data = await get_flood_zone(inp.property_address)
                tools_used.append("fema_flood")
            except RuntimeError as e:
                print(f"[PROPERTY_AGENT] FEMA lookup failed: {e}")
                flood_data = {"error": str(e)}
        else:
            writer({"type": "thinking", "message": "No property address provided — skipping flood check..."})

            
        # ── HOA document analysis
        if hoa_pdf_bytes:
            await log_tool_called(uid, phase_id, "hoa_analyzer")
            writer({"type": "thinking", "message": "Analyzing HOA document..."})
            try:
                hoa_data = await analyze_hoa_document(
                    pdf_bytes=hoa_pdf_bytes,
                    uid=uid,
                    property_address=inp.property_address,
                )
                tools_used.append("hoa_analyzer")
                writer({
                    "type": "thinking",
                    "message": f"Analyzed {hoa_data['pages_analyzed']} pages, "
                               f"found {hoa_data['high_risk_count']} high-risk items...",
                })
            except RuntimeError as e:
                print(f"[PROPERTY_AGENT] HOA analysis failed: {e}")
                hoa_data = {"error": str(e)}

        # ── Build prompt 
        writer({"type": "thinking", "message": "Gavvy is thinking..."})

        flood_section = _format_flood_section(flood_data, inp.property_address)
        hoa_section   = _format_hoa_section(hoa_data)

        prompt = f"""
            User profile:
            - Property address: {inp.property_address}
            - Budget: ${inp.budget:,.0f}
            - Location: {inp.location or "not provided"}

            {flood_section}

            {hoa_section}

            User's question:
            {user_message}

            Populate all fields in the response schema.
            For flood data, use the FEMA zone information above.
            For HOA findings, map each finding to an HOAFinding with accurate risk levels.
            Explain practical dollar impact for high-risk findings.
            """.strip()

        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ]

        # ── Structured LLM output 
        structured_llm = llm.with_structured_output(PropertyOutput)
        output: PropertyOutput = await structured_llm.ainvoke(messages)

        # ── Build sources 
        sources = []
        if flood_data and "error" not in flood_data:
            sources.append({
                "source":  "FEMA National Flood Hazard Layer",
                "url":     "https://msc.fema.gov/portal/home",
                "snippet": f"Zone {flood_data['flood_zone']} — {flood_data['risk_level']} risk",
            })
        if hoa_data and "error" not in hoa_data:
            sources.append({
                "source":  "HOA Document (user upload)",
                "url":     "",
                "snippet": f"{hoa_data['pages_analyzed']} pages analyzed, "
                           f"{hoa_data['high_risk_count']} high-risk findings",
            })

        await log_agent_completed(uid, phase_id, tools_used=tools_used)

        return {
            "messages": [AIMessage(content=output.summary)],
            "tool_results": output.model_dump(),
            "sources":       sources,
            "awaiting_human": False,
        }

    except Exception as e:
        await log_agent_error(uid, phase_id, str(e))
        raise


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


def _extract_last_user_message(state: GavvyState) -> str:
    messages = state.get("messages", [])
    if not messages:
        return "Tell me about this property."
    last = messages[-1]
    if hasattr(last, "content"):
        return last.content
    if isinstance(last, dict):
        return last.get("content", "")
    return "Tell me about this property."