"""Human approval CLI for cost recommendations (the approval half of the workflow).

    uv run mcca-review                       # list current recommendations + their status
    uv run mcca-review approve <key> --by me # record an approval (intent only)
    uv run mcca-review dismiss <key>
    uv run mcca-review snooze  <key>

A decision records INTENT only — nothing is executed against infrastructure. The agent can
read these statuses but cannot set them; only this human-run CLI records decisions.
"""

from __future__ import annotations

import argparse
from datetime import date, timedelta

from mcca.config import get_settings
from mcca.logging import configure_logging
from mcca.optimization.service import decide, review_recommendations
from mcca.warehouse.postgres import PostgresRepository

_STATUS = {"approve": "APPROVED", "dismiss": "DISMISSED", "snooze": "SNOOZED"}


def _first_of_month(d: date) -> date:
    return d.replace(day=1)


def _minus_months(d: date, months: int) -> date:
    total = (d.year * 12 + (d.month - 1)) - months
    return date(total // 12, total % 12 + 1, 1)


def _window(months: int) -> tuple[date, date]:
    end = _first_of_month(date.today())
    return _minus_months(end, months), end


def _print_list(repo: PostgresRepository, start: date, end: date) -> None:
    result = review_recommendations(repo, start, end)
    counts = " · ".join(f"{k}:{v}" for k, v in sorted(result.counts.items())) or "none"
    print(f"Recommendations {start} to {end} (exclusive) — {counts}\n")
    print(f"{'KEY':<14}{'STATUS':<10}{'SEV':<8}SUMMARY")
    for r in result.recommendations:
        print(f"{r.key:<14}{r.status:<10}{r.severity:<8}{r.summary[:80]}")
    print("\nDecide with:  uv run mcca-review approve|dismiss|snooze <KEY> [--by NAME] [--note …]")


def main() -> None:
    parser = argparse.ArgumentParser(description="Review and decide on cost recommendations.")
    parser.add_argument("--months", type=int, default=3, help="History window (default 3).")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("list", help="List current recommendations and their status (default).")
    for name in ("approve", "dismiss", "snooze"):
        p = sub.add_parser(name, help=f"{name.capitalize()} a recommendation by key.")
        p.add_argument("key", help="Recommendation key (or a unique prefix).")
        p.add_argument("--by", default=None, help="Who made the decision.")
        p.add_argument("--note", default=None, help="Optional note.")
        if name == "snooze":
            p.add_argument("--until", default=None, help="Snooze until YYYY-MM-DD (re-surfaces after).")
            p.add_argument("--days", type=int, default=None, help="Snooze for N days from today.")
    args = parser.parse_args()

    configure_logging()
    get_settings()
    repo = PostgresRepository()
    start, end = _window(args.months)

    if args.command in _STATUS:
        snooze_until = None
        if args.command == "snooze":
            if getattr(args, "until", None):
                snooze_until = date.fromisoformat(args.until)
            elif getattr(args, "days", None):
                snooze_until = date.today() + timedelta(days=args.days)
        rec = decide(
            repo,
            start,
            end,
            args.key,
            _STATUS[args.command],
            decided_by=args.by,
            note=args.note,
            snooze_until=snooze_until,
        )
        suffix = f" (until {snooze_until})" if snooze_until else ""
        print(f"Recorded {rec.status} for {rec.key}{suffix}: {rec.summary}")
        print("(Intent recorded only — nothing was executed.)")
    else:
        _print_list(repo, start, end)


if __name__ == "__main__":
    main()
