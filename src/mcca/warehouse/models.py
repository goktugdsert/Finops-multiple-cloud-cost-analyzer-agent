"""Pydantic domain models mirroring the FOCUS warehouse schema.

`FocusRecord` is the typed shape that normalization produces and the warehouse stores.
The four attribution fields default to ``UNATTRIBUTED`` so normalization code can never
silently omit them — untagged spend is surfaced honestly rather than dropped.

Core principle: these models CARRY numbers that were produced by deterministic
ingestion/queries. They are not a source of figures — the LLM never fabricates values
here. Costs use ``Decimal`` (not float) to preserve exactness.
"""

from __future__ import annotations

import hashlib
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

    # --- Restatement / reconciliation ---------------------------------------
    # Did the source mark this line an estimate? Estimates are later restated to a final;
    # ingestion upserts on natural_key() so the final overwrites the estimate in place.
    is_estimated: bool = False

    # --- Raw provider tags ---------------------------------------------------
    tags: dict[str, str] | None = None

    # --- ATTRIBUTION (honest fallback, never omitted) -----------------------
    x_team: str = Field(default=UNATTRIBUTED)
    x_service: str = Field(default=UNATTRIBUTED)
    x_environment: str = Field(default=UNATTRIBUTED)
    x_owner: str = Field(default=UNATTRIBUTED)

    # AWS BlendedCost, captured for visibility only (FOCUS has no blended measure). billed_cost
    # is always unblended; this exists so blended-vs-unblended can be compared, never summed
    # as the bill. None for Azure/GCP, which don't report a blended figure.
    x_blended_cost: Decimal | None = None

    # --- Provenance ----------------------------------------------------------
    source_system: str | None = None

    def natural_key(self) -> str:
        """Stable hash of this line's natural billing identity (NOT its cost measures).

        Two records that describe the *same* billing line — same provider, account, day,
        service, charge type, SKU/resource/region, commitment — share a key even if their
        amounts differ. That is exactly what lets re-ingestion reconcile: an estimate and
        its later final restatement collide on this key and the final overwrites the
        estimate, instead of both accumulating. The cost/quantity measures are deliberately
        excluded so a restated amount does not mint a new row.
        """
        parts = [
            self.source_system,
            self.provider_name,
            self.billing_account_id,
            self.sub_account_id,
            self.charge_period_start.date().isoformat(),
            self.service_name,
            self.charge_category,
            self.charge_description,
            self.sku_id,
            self.resource_id,
            self.region_id,
            self.commitment_discount_id,
        ]
        # \x1f (unit separator) can't occur in these values; None -> distinct sentinel.
        canonical = "\x1f".join("\x00" if p is None else str(p) for p in parts)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
