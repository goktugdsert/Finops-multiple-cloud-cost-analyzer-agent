"""Fixed query definitions. Importing this package registers every query.

One module per theme: spend (visibility), attribution, trends. Add new validated
queries here; they self-register via `mcca.queries.registry.register`.
"""

from mcca.queries.definitions import attribution, spend, trends  # noqa: F401
