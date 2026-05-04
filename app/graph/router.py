"""
Phase reouter - reads phase_id from state and returns the next node name,
it only reads state and returns a routing decision
"""

from app.graph.state import GavvyState

PHASE_TO_AGENT: dict[str, str] = {
    "readiness": "readiness_agent",
    "mortgage": "mortgage_agent",
    "property": "property_agent",
    "contract":  "contract_agent",
    "closing":   "contract_agent",
}

DEFAULT_AGENT = "readiness_agent"

def phase_router(state: GavvyState) -> str:
    """
    Return the name of the next node to execute
    uses this as the edge condition in add_conditional_edges()
    """

    phase = state.get("phase_id", "readiness")
    return PHASE_TO_AGENT.get(phase, DEFAULT_AGENT)