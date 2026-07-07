"""Routing (the 'route to an owner with a recommended action' stage of the loop).

Turns deterministic findings — cost spikes, steady waste, budget breaches — into
owner-routed, recommended actions. READ-ONLY and recommend-only: it never executes a
change; a human approves. Recommendation text is templated (not LLM-authored), and every
figure comes from the detection/budget/attribution layers.
"""

from mcca.routing.router import Finding, RoutingReport, build_findings, route

__all__ = ["Finding", "RoutingReport", "build_findings", "route"]
