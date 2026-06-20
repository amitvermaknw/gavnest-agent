"""
Contract agent — Phases 4-5: Make an Offer + Under Contract.

Input:  ContractInput  (validated from user_profile)
Output: ContractOutput (structured LLM output via with_structured_output)
"""
from __future__ import annotations

from langchain_core.messages import AIMessage, SystemMessage, HumanMessage
from langgraph.config import get_stream_writer

from app.graph.state import GavvyState
from app.graph.llm import get_llm
from app.graph.schemas import ContractInput, ContractOutput
from app.services.event_logger import (
    log_agent_started,
    log_agent_completed,
    log_agent_error,
    log_tool_called,
)


SYSTEM_PROMPT = """You are Gavvy, a friendly home-buying guide built by GavNest.
Your role is education only — not legal advice.

Rules:
- Never tell the user to waive a contingency.
- Highlight any waived buyer protections as high risk.
- Use plain English. Define every legal term.
- Show closing costs as concrete dollar amounts.
- Populate every field in the response schema accurately.

You are helping with Phases 4-5: Making an Offer and Being Under Contract.
Topics: contract clauses, contingencies, inspection rights, closing costs,
cash-to-close calculation, title insurance, earnest money."""


async def contract_agent(state: GavvyState) -> dict:
    writer = get_stream_writer()
    llm = get_llm()
    uid = state.get("uid", "unknown")
    phase_id = state.get("phase_id", "contract")
    user_message = _extract_last_user_message(state)

    await log_agent_started(uid, phase_id, user_message)
    writer({"type": "thinking", "message": "Reading your contract..."})

    try:
        # ── Validate input 
        try:
            inp = ContractInput.from_profile(state.get("user_profile", {}))
        except ValueError as e:
            raise RuntimeError(f"Invalid profile data: {e}") from e

        contract_pdf_bytes = state.get("tool_results", {}).get("contract_pdf_bytes")
        contract_text      = state.get("tool_results", {}).get("contract_text", "")
        tools_used         = []

        # ── Analyze contract PDF if uploaded 
        if contract_pdf_bytes and not contract_text:
            await log_tool_called(uid, phase_id, "pdf_rag")
            writer({"type": "thinking", "message": "Extracting contract text..."})
            try:
                from app.tools.hoa_analyzer import _extract_text_from_pdf
                pages = _extract_text_from_pdf(contract_pdf_bytes)
                contract_text = "\n\n".join([p["text"] for p in pages])
                tools_used.append("pdf_rag")
            except Exception as e:
                print(f"[CONTRACT_AGENT] PDF extraction failed: {e}")

        writer({"type": "thinking", "message": "Gavvy is analyzing the contract..."})


        # ── Build prompt
        purchase_price = inp.offer_price or inp.budget
        closing_cost_estimate = purchase_price * 0.03   # ~3% rule of thumb

        contract_section = (
            f"Contract text (first 3000 chars):\n{contract_text[:3000]}"
            if contract_text
            else "No contract uploaded — provide general education on contract clauses."
        )

        prompt = f"""
            User profile:
            - Property address: {inp.property_address or "not provided"}
            - Offer/purchase price: ${purchase_price:,.0f}
            - Location (state): {inp.location or "not provided"}
            - Estimated closing costs (~3%): ${closing_cost_estimate:,.0f}

            {contract_section}

            User's question:
            {user_message}

            Populate the response schema:
            - Analyze any contract clauses found in the text
            - Calculate closing cost breakdown for the purchase price and state
            - Flag any waived contingencies as high risk
            - Provide negotiation tips where applicable
            - Explain everything in plain English
            """.strip()

        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ]

        # ── Structured LLM output 
        structured_llm = llm.with_structured_output(ContractOutput)
        output: ContractOutput = await structured_llm.ainvoke(messages)

        await log_agent_completed(uid, phase_id, tools_used=tools_used)

        sources = []
        if contract_text:
            sources.append({
                "source":  "Purchase Agreement (user upload)",
                "url":     "",
                "snippet": f"Contract analyzed for {inp.property_address}",
            })

        return {
            "messages": [AIMessage(content=output.summary)],
            "tool_results": output.model_dump(),
            "sources":       sources,
            "awaiting_human": False,
        }

    except Exception as e:
        await log_agent_error(uid, phase_id, str(e))
        raise


def _extract_last_user_message(state: GavvyState) -> str:
    messages = state.get("messages", [])
    if not messages:
        return "Tell me about this contract."
    last = messages[-1]
    if hasattr(last, "content"):
        return last.content
    if isinstance(last, dict):
        return last.get("content", "")
    return "Tell me about this contract."