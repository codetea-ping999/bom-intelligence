"""Adapter contracts, routing, and batch runs."""

from bom_intelligence.pipeline.adapters import default_registry
from bom_intelligence.pipeline.contracts import (
    AdapterRegistry,
    DocumentExtractor,
    DocumentProfiler,
    DocumentRef,
    ExtractionResult,
    RouteStrategy,
    StrategyDecision,
)
from bom_intelligence.pipeline.router import route
from bom_intelligence.pipeline.run import (
    DocumentResult,
    analyze_directory,
    process_document,
    read_results,
)

__all__ = [
    "AdapterRegistry",
    "DocumentExtractor",
    "DocumentProfiler",
    "DocumentRef",
    "DocumentResult",
    "ExtractionResult",
    "RouteStrategy",
    "StrategyDecision",
    "analyze_directory",
    "default_registry",
    "process_document",
    "read_results",
    "route",
]
