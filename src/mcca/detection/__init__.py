"""Detection (the 'detect' stage of the loop).

Deterministic detectors over grounded query results: cost SPIKES (days far above a
trailing baseline) and STEADY structural spend (flat, persistent cost worth an efficiency
review). No LLM — findings are reproducible calculations.
"""

from mcca.detection.detector import (
    DetectionReport,
    Spike,
    SteadyCost,
    detect_spikes,
    detect_steady_costs,
)
from mcca.detection.service import detect

__all__ = [
    "DetectionReport",
    "Spike",
    "SteadyCost",
    "detect",
    "detect_spikes",
    "detect_steady_costs",
]
