"""LangChain tool wrappers over the deterministic query + calculation layer.

These tools are the ONLY numeric source the agent has. Each tool runs a registered
query (or a pure calculation) and returns figures with their provenance. The agent
cannot obtain a number any other way.
"""
