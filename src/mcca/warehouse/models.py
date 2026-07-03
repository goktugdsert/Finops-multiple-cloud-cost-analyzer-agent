"""Pydantic domain models mirroring the FOCUS warehouse schema.

`FocusRecord` is the typed shape that normalization produces and the warehouse stores.
The four attribution fields default to ``UNATTRIBUTED`` so normalization code can never
silently omit them — untagged spend is surfaced honestly rather than dropped.

Core principle: these models CARRY numbers that were produced by deterministic
ingestion/queries. They are not a source of figures — the LLM never fabricates values
here. Costs use ``Decimal`` (not float) to preserve exactness.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from mcca.warehouse.schema import UNATTRIBUTED


class FocusRecord(BaseModel):
    """One normalized FOCUS cost line, ready to persist to the warehouse."""

    model_config = ConfigDict(extra="forbid")

    # --- Cost measures -------------------------------------------------------
    billed_cost: Decimal
    effective_cost: Decimal
    list_cost: Decimal | None = None
    contracted_cost: Decimal | None = None
    billing_currency: str

    # --- Accounts ------------------------------------------------------------
    billing_account_id: str
    billing_account_name: str | None = None
    sub_account_id: str | None = None
    sub_account_name: str | None = None

    # --- Time ----------------------------------------------------------------
    billing_period_start: datetime
    billing_period_end: datetime
    charge_period_start: datetime
    charge_period_end: datetime

    # --- Charge classification ----------------------------------------------
    charge_category: str
    charge_class: str | None = None
    charge_description: str | None = None
    charge_frequency: str | None = None

    # --- Commitment discounts (RIs / Savings Plans) --------------------------
    commitment_discount_id: str | None = None
    commitment_discount_category: str | None = None
    commitment_discount_name: str | None = None
    commitment_discount_status: str | None = None
    commitment_discount_type: str | None = None

    # --- Service / SKU / location -------------------------------------------
    provider_name: str
    publisher_name: str | None = None
    service_category: str | None = None
    service_name: str | None = None
    sku_id: str | None = None
    sku_price_id: str | None = None
    region_id: str | None = None
    region_name: str | None = None
    resource_id: str | None = None
    resource_name: str | None = None
    resource_type: str | None = None

    # --- Usage / pricing -----------------------------------------------------
    consumed_quantity: Decimal | None = None
    consumed_unit: str | None = None
    pricing_quantity: Decimal | None = None
    pricing_unit: str | None = None
    list_unit_price: Decimal | None = None
    contracted_unit_price: Decimal | None = None
    pricing_category: str | None = None

    # --- Raw provider tags ---------------------------------------------------
    tags: dict[str, str] | None = None

    # --- ATTRIBUTION (honest fallback, never omitted) -----------------------
    x_team: str = Field(default=UNATTRIBUTED)
    x_service: str = Field(default=UNATTRIBUTED)
    x_environment: str = Field(default=UNATTRIBUTED)
    x_owner: str = Field(default=UNATTRIBUTED)

    # --- Provenance ----------------------------------------------------------
    source_system: str | None = None
