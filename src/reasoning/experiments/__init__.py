"""
Experiment framework for reasoning methods.

Provides tools for:
- Running experiments across methods
- Comparing method performance
- Visualizing results
"""

from .runner import ExperimentRunner
from .adapters import IRCoTAdapter, DecompositionAdapter

__all__ = [
    "ExperimentRunner",
    "IRCoTAdapter",
    "DecompositionAdapter",
]

