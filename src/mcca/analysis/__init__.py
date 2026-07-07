"""Analysis (the 'explain why' stage of the loop).

Decompose a spend change between two periods into per-service drivers, so a rise or fall
can be attributed to the services that moved. Grounded in the fixed query layer.
"""

from mcca.analysis.drivers import ChangeExplanation, Driver, explain_change

__all__ = ["ChangeExplanation", "Driver", "explain_change"]
