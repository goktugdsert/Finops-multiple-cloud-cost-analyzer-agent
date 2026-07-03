"""Warehouse data-access layer.

This package is the ONLY place that knows how cost data is physically stored. Agent
and query logic depend on the `WarehouseRepository` interface (repository.py), never
on Postgres directly — so the store can be swapped for BigQuery/Snowflake later by
adding a new implementation, without touching agent logic.
"""
