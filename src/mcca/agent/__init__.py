"""LangGraph agent orchestration.

The agent imports ONLY the tools layer (plus config/logging). It never imports
ingestion, boto3, or raw SQL — the LLM's only path to a number is a tool call. This
import boundary is what makes the core principle structural, not just a prompt rule.
"""
