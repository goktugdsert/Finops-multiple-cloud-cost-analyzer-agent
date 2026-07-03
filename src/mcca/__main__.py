"""CLI entry point (stub).

Wired to the agent in build step 4/7. For now it just confirms config loads and the
warehouse is reachable — no agent, no numbers.
"""

from __future__ import annotations

from mcca.config import get_settings
from mcca.logging import configure_logging


def main() -> None:
    configure_logging()
    settings = get_settings()
    print(f"mcca-agent skeleton. Warehouse: {settings.database_url.rsplit('@', 1)[-1]}")
    print("Agent not wired yet (build step 4). This session is scaffold only.")


if __name__ == "__main__":
    main()
