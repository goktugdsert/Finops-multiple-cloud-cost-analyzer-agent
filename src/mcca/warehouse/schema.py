"""FOCUS-schema warehouse tables, defined as SQLAlchemy Core metadata.

FOCUS (FinOps Open Cost & Usage Specification) 1.x is the normalized target schema so
that "a dollar means the same thing" across AWS, Azure, and GCP. This module defines a
representative subset of the FOCUS core columns needed for v1, plus a reserved
ATTRIBUTION block (`x_*` custom columns) that exists from row one.

Attribution: every row carries team / service / environment / owner. When source data
lacks the tags to fill them, they default to the literal ``'unattributed'`` — untagged
spend is shown honestly, never dropped and never guessed. The *policy* that maps cloud
tags to these columns is deferred (see CLAUDE.md); here we only reserve the columns and
the fallback.

Core principle: this schema is a destination for numbers produced by deterministic
ingestion/queries. The LLM never writes to or invents values in it.
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Index,
    MetaData,
    Numeric,
    Table,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

# Sentinel used across the whole codebase for spend that could not be attributed.
UNATTRIBUTED = "unattributed"

metadata = MetaData()

# Money is stored as NUMERIC to avoid floating-point drift. FOCUS defines several
# cost measures; we keep the ones that matter for correct v1 reporting:
#   billed_cost      — invoiced amount (what shows on the bill)
#   effective_cost   — amortized cost incl. commitment discounts (RIs/SPs), credits
#   list_cost        — cost at public list price, before any discount
#   contracted_cost  — cost at negotiated/contracted price
_MONEY = Numeric(20, 10)

focus_costs = Table(
    "focus_costs",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    # --- Cost measures -------------------------------------------------------
    Column("billed_cost", _MONEY, nullable=False),
    Column("effective_cost", _MONEY, nullable=False),
    Column("list_cost", _MONEY, nullable=True),
    Column("contracted_cost", _MONEY, nullable=True),
    Column("billing_currency", Text, nullable=False),
    # --- Accounts ------------------------------------------------------------
    Column("billing_account_id", Text, nullable=False),
    Column("billing_account_name", Text, nullable=True),
    Column("sub_account_id", Text, nullable=True),
    Column("sub_account_name", Text, nullable=True),
    # --- Time ----------------------------------------------------------------
    Column("billing_period_start", DateTime(timezone=True), nullable=False),
    Column("billing_period_end", DateTime(timezone=True), nullable=False),
    Column("charge_period_start", DateTime(timezone=True), nullable=False),
    Column("charge_period_end", DateTime(timezone=True), nullable=False),
    # --- Charge classification ----------------------------------------------
    Column("charge_category", Text, nullable=False),  # Usage|Purchase|Tax|Credit|Adjustment
    Column("charge_class", Text, nullable=True),  # e.g. Correction
    Column("charge_description", Text, nullable=True),
    Column("charge_frequency", Text, nullable=True),  # One-Time|Recurring|Usage-Based
    # --- Commitment discounts (RIs / Savings Plans) --------------------------
    Column("commitment_discount_id", Text, nullable=True),
    Column("commitment_discount_category", Text, nullable=True),  # Spend|Usage
    Column("commitment_discount_name", Text, nullable=True),
    Column("commitment_discount_status", Text, nullable=True),  # Used|Unused
    Column("commitment_discount_type", Text, nullable=True),  # e.g. Reserved Instance
    # --- Service / SKU / location -------------------------------------------
    Column("provider_name", Text, nullable=False),  # AWS|Azure|GCP
    Column("publisher_name", Text, nullable=True),
    Column("service_category", Text, nullable=True),  # e.g. Compute, Storage
    Column("service_name", Text, nullable=True),  # e.g. Amazon EC2
    Column("sku_id", Text, nullable=True),
    Column("sku_price_id", Text, nullable=True),
    Column("region_id", Text, nullable=True),
    Column("region_name", Text, nullable=True),
    Column("resource_id", Text, nullable=True),
    Column("resource_name", Text, nullable=True),
    Column("resource_type", Text, nullable=True),
    # --- Usage / pricing -----------------------------------------------------
    Column("consumed_quantity", Numeric(30, 10), nullable=True),
    Column("consumed_unit", Text, nullable=True),
    Column("pricing_quantity", Numeric(30, 10), nullable=True),
    Column("pricing_unit", Text, nullable=True),
    Column("list_unit_price", Numeric(30, 15), nullable=True),
    Column("contracted_unit_price", Numeric(30, 15), nullable=True),
    Column("pricing_category", Text, nullable=True),  # Standard|Committed|On-Demand
    # --- Restatement / reconciliation ---------------------------------------
    # Whether the source reported this line as an estimate (subject to a later final
    # restatement). Carried through so re-ingestion can overwrite an estimate with its
    # final. `line_key` is a stable hash of the line's natural billing identity (NOT its
    # cost measures); it is UNIQUE so re-ingesting a period upserts in place instead of
    # duplicating. See FocusRecord.natural_key().
    Column("is_estimated", Boolean, nullable=False, server_default=text("false")),
    Column("line_key", Text, nullable=False),
    # --- Raw provider tags (JSON) -------------------------------------------
    Column("tags", JSONB, nullable=True),
    # --- ATTRIBUTION (custom x_ columns, reserved from row one) -------------
    Column("x_team", Text, nullable=False, server_default=UNATTRIBUTED),
    Column("x_service", Text, nullable=False, server_default=UNATTRIBUTED),
    Column("x_environment", Text, nullable=False, server_default=UNATTRIBUTED),
    Column("x_owner", Text, nullable=False, server_default=UNATTRIBUTED),
    # --- Provenance ----------------------------------------------------------
    Column("ingested_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("source_system", Text, nullable=True),  # e.g. aws.cost_explorer
    # Indexes for the common reporting access patterns.
    Index("ix_focus_costs_charge_period", "charge_period_start", "charge_period_end"),
    Index("ix_focus_costs_provider_service", "provider_name", "service_name"),
    Index("ix_focus_costs_attribution", "x_team", "x_environment"),
    # Natural billing-line identity: upsert target for estimate->final reconciliation.
    UniqueConstraint("line_key", name="uq_focus_costs_line_key"),
)

# Budgets are user-set monthly targets (not derived cost figures) that spend is tracked
# against. Scoped so a budget can later apply to a service/team/environment; v1 uses
# ('total', 'all'). One recurring monthly amount per scope.
budgets = Table(
    "budgets",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("scope_type", Text, nullable=False),  # total | service | team | environment
    Column("scope_value", Text, nullable=False, server_default="all"),
    Column("monthly_amount", Numeric(20, 10), nullable=False),
    Column("currency", Text, nullable=False, server_default="USD"),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("scope_type", "scope_value", name="uq_budget_scope"),
)
