"""Registry and runner for the fixed, validated cost-query set.

Every cost figure the agent can return originates from a query registered here. This is
NOT open-ended text-to-SQL: each query is authored as a SQLAlchemy Core statement builder
with a declared parameter contract, validated, and referenced by name. The LLM chooses a
query name and parameter values; it never writes SQL.

`run_query` returns a `QueryResult` that carries the query name and the exact parameters
alongside the rows, so every number is traceable to the query that produced it — the core
principle, enforced by construction.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy import Select

    from mcca.warehouse.repository import WarehouseRepository

# Cost measures a caller may aggregate. Restricting to this allowlist keeps the metric
# choice deterministic and prevents arbitrary column selection.
COST_METRICS: tuple[str, ...] = ("billed_cost", "effective_cost")


@dataclass(frozen=True)
class QueryParam:
    """Declared parameter for a query: name, whether required, default, and choices."""

    name: str
    required: bool = False
    default: Any = None
    choices: tuple[Any, ...] = ()


@dataclass(frozen=True)
class QueryDefinition:
    """A fixed, validated query: its parameter contract and a Core statement builder."""

    name: str
    description: str
    params: tuple[QueryParam, ...]
    build: Callable[[dict[str, Any]], Select]


@dataclass(frozen=True)
class QueryResult:
    """Rows plus the provenance (query name + validated params) that produced them."""

    name: str
    params: dict[str, Any]
    rows: list[dict[str, Any]]


REGISTRY: dict[str, QueryDefinition] = {}
_loaded = False


def register(definition: QueryDefinition) -> QueryDefinition:
    """Add a query definition to the registry (used by definition modules)."""
    if definition.name in REGISTRY:
        raise ValueError(f"Duplicate query name: {definition.name!r}")
    REGISTRY[definition.name] = definition
    return definition


def _ensure_loaded() -> None:
    """Import the definition modules once so they self-register."""
    global _loaded
    if not _loaded:
        from mcca.queries import definitions  # noqa: F401  (import triggers registration)

        _loaded = True


def list_queries() -> list[QueryDefinition]:
    _ensure_loaded()
    return sorted(REGISTRY.values(), key=lambda d: d.name)


def get_query(name: str) -> QueryDefinition:
    """Look up a registered query by name."""
    _ensure_loaded()
    try:
        return REGISTRY[name]
    except KeyError as exc:
        known = ", ".join(sorted(REGISTRY)) or "(none)"
        raise KeyError(
            f"Unknown query {name!r}. Only registered, validated queries may run; "
            f"arbitrary SQL is not permitted. Known queries: {known}."
        ) from exc


def _coerce(value: Any) -> Any:
    """Coerce ISO date strings to `date` so callers may pass either."""
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return value
    return value


def validate_params(definition: QueryDefinition, params: dict[str, Any]) -> dict[str, Any]:
    """Validate/normalize params against the definition's contract.

    Fills defaults, enforces required params and declared choices, and rejects unknown
    parameter names — so the agent cannot smuggle in unexpected inputs.
    """
    declared = {p.name: p for p in definition.params}
    unknown = set(params) - set(declared)
    if unknown:
        raise ValueError(f"Unknown parameter(s) for {definition.name!r}: {sorted(unknown)}")

    resolved: dict[str, Any] = {}
    for spec in definition.params:
        if spec.name in params and params[spec.name] is not None:
            value = _coerce(params[spec.name])
        elif spec.required:
            raise ValueError(f"Missing required parameter {spec.name!r} for {definition.name!r}")
        else:
            value = spec.default
        if spec.choices and value is not None and value not in spec.choices:
            raise ValueError(
                f"Invalid value {value!r} for {spec.name!r}; choose from {list(spec.choices)}"
            )
        resolved[spec.name] = value
    return resolved


def run_query(
    repo: WarehouseRepository, name: str, params: dict[str, Any] | None = None
) -> QueryResult:
    """Validate params, build the registered statement, execute it, and return rows."""
    definition = get_query(name)
    validated = validate_params(definition, params or {})
    statement = definition.build(validated)
    rows = repo.execute(statement)
    return QueryResult(name=name, params=validated, rows=rows)


# Shared helpers for definition modules ---------------------------------------------------
def metric_param(default: str = "billed_cost") -> QueryParam:
    """A standard `metric` parameter restricted to the cost-measure allowlist."""
    return QueryParam("metric", required=False, default=default, choices=COST_METRICS)
