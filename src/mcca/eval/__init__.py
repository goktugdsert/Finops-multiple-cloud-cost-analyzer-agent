"""A small curated eval set for the agent.

Grades whether the agent selects the right cost tool(s) for a question and never answers a
cost question without querying (guarding the core principle: no ungrounded figures). Runs
through the same LangGraph agent, so LangSmith traces (if enabled) are captured for free.
"""
