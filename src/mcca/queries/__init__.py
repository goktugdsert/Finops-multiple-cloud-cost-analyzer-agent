"""Deterministic query layer — the fixed, pre-tested question set.

Every cost figure the agent can return originates from a query registered here. This is
NOT open-ended text-to-SQL: queries are authored, reviewed, and validated against the
AWS Cost Explorer console, then referenced by name. The LLM selects a query and its
parameters; it never writes SQL.
"""
