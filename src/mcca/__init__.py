"""mcca — Multi-Cloud Cost Analyzer agent.

Read-only FinOps agent. Core principle (non-negotiable): the LLM orchestrates and
explains, but NEVER produces a cost figure. Every number returned to a user comes
from a deterministic tool (a validated SQL query or a calculation) over the
FOCUS-schema warehouse. If a number can't be traced to a query, it is not shown.
"""

__version__ = "0.1.0"
