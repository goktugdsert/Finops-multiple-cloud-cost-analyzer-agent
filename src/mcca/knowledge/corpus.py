"""Curated qualitative knowledge for the RAG layer.

STRICT RULE: these documents are QUALITATIVE only — definitions, concepts, and this project's
policies. They contain NO cost figures (no dollar amounts). RAG must never be a source of a
number; every cost figure comes from a deterministic query. A unit test asserts no document
here contains a currency figure, so the knowledge base cannot smuggle one in.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Document:
    id: str
    title: str
    source: str
    text: str


DOCUMENTS: list[Document] = [
    Document(
        "cost-measures",
        "FOCUS cost measures: list, contracted, billed, effective",
        "docs/cost-measures",
        (
            "FOCUS defines several cost measures that form a discount stack, from highest to "
            "lowest: list cost, contracted cost, billed cost, and effective cost.\n\n"
            "List cost is the public on-demand price before any discount. Contracted cost is "
            "the price at your negotiated (contracted) rate — for example after an enterprise "
            "discount program — but before commitment discounts. Billed cost is the amount "
            "actually invoiced, after commitment discounts such as reservations are applied; "
            "it is the unblended amount. Effective cost is the amortized cost, spreading "
            "commitment purchases across the usage they cover.\n\n"
            "Blended cost is an AWS consolidated-billing average across a member-account "
            "family. This project never bills blended: the billed figure is always unblended. "
            "Blended is captured separately for visibility only."
        ),
    ),
    Document(
        "commitment-discounts",
        "Commitment discounts: Reserved Instances, Savings Plans, CUDs",
        "docs/commitment-discounts",
        (
            "Commitment discounts trade a usage or spend commitment for a lower rate. Reserved "
            "Instances (RIs) commit to a specific instance type; Savings Plans commit to an "
            "hourly spend and cover matching usage; Google's Committed Use Discounts (CUDs) "
            "are the equivalent, applied as credits inside each billing row.\n\n"
            "Commitments lower the effective (amortized) cost rather than the on-demand list "
            "cost. Covered usage may be billed at a reduced or zero amount, with the "
            "commitment fee amortized back onto that usage so amortized totals stay consistent. "
            "Under-used commitments show as unused-reservation adjustments."
        ),
    ),
    Document(
        "focus-schema",
        "FOCUS: one normalized schema across clouds",
        "docs/focus",
        (
            "FOCUS (the FinOps Open Cost and Usage Specification) is a vendor-neutral schema "
            "for cloud billing and usage. This project normalizes AWS, Azure, and GCP billing "
            "into one FOCUS-shaped warehouse so a dollar means the same thing on every cloud.\n\n"
            "Each line carries a charge category (Usage, Purchase, Tax, Credit, Adjustment), a "
            "provider and service, time periods, commitment-discount metadata, and custom "
            "attribution columns. Normalizing to FOCUS is where cross-cloud correctness is "
            "earned: discounts, credits, amortization, and blended-versus-unblended must all "
            "map consistently."
        ),
    ),
    Document(
        "attribution-tagging",
        "Attribution, tagging, and unattributed spend",
        "docs/attribution",
        (
            "Every cost line is attributed to a team, service, environment, and owner via "
            "cost-allocation tags mapped onto FOCUS custom columns. When a line lacks a tag, "
            "the value falls back to 'unattributed' rather than being guessed.\n\n"
            "Showing untagged spend honestly as unattributed is deliberate: it makes tagging "
            "gaps visible instead of hiding shared or orphaned cost. Improving attribution "
            "means tagging more resources at the source, not inventing an owner."
        ),
    ),
    Document(
        "allocation",
        "Cost allocation: fully-loaded team cost",
        "docs/allocation",
        (
            "Allocation redistributes the shared, unattributed pool across teams so each team "
            "sees a fully-loaded cost. Methods include proportional (split by each team's "
            "direct spend, the common default), even (equal split), and weighted (fixed "
            "shares).\n\n"
            "Allocation is a derived view: the warehouse is never rewritten, so raw data still "
            "shows unattributed spend honestly. Allocated shares always reconcile exactly to "
            "the shared pool — no cost is created or lost in the split."
        ),
    ),
    Document(
        "budgets-forecasting",
        "Budgets and forecasting",
        "docs/budgets-forecasting",
        (
            "A budget is a monthly target that spend is tracked against. Budget status "
            "combines month-to-date actuals with a forecast of the remaining days and compares "
            "the projection to the target, reporting on-track, at-risk, or over.\n\n"
            "Forecasts use a seasonal time-series model over daily history and always show an "
            "uncertainty (prediction) interval — a forecast is never a point certainty. The "
            "model captures a weekly cycle only; it has no awareness of holidays or one-off "
            "calendar events, so a high or low day reflects the weekday/weekend pattern, not a "
            "holiday."
        ),
    ),
    Document(
        "governance-approval",
        "Governance policies and the approval workflow",
        "docs/governance",
        (
            "Governance policies are declarative rules — for example limits on unattributed "
            "spend, per-team caps, or restricted services. The engine evaluates spend against "
            "them and flags violations with a recommended action. It is recommend-only and "
            "never enforces or changes anything.\n\n"
            "Recommendations from detection and governance can be reviewed and given a human "
            "decision: approve, dismiss, or snooze. A decision records intent only and is never "
            "an action against infrastructure. The assistant can report decision status but "
            "cannot approve — only a human does that."
        ),
    ),
    Document(
        "trust-boundary",
        "The trust boundary: numbers only from deterministic queries",
        "docs/trust-boundary",
        (
            "The core principle is that the language model orchestrates and explains but never "
            "produces a cost figure from its own reasoning. Every number comes from a "
            "deterministic tool — a validated query or a calculation. If a figure cannot be "
            "traced to a query, it is not shown.\n\n"
            "This knowledge base answers qualitative questions only. It must never be used to "
            "produce a cost amount; for any dollar figure, the assistant uses the numeric query "
            "tools. The system is read-only: it recommends actions but never modifies or "
            "terminates infrastructure."
        ),
    ),
]
