"""Gold-set evaluation harness."""

from bom_intelligence.evaluation.harness import (
    GoldDocument,
    GoldRecord,
    evaluate,
    load_gold,
    write_gold,
)

__all__ = ["GoldDocument", "GoldRecord", "evaluate", "load_gold", "write_gold"]
