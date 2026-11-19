"""Structural document profilers."""

from bom_intelligence.profiler.common import KeywordHit, ReadError
from bom_intelligence.profiler.excel import ExcelProfile, profile_excel
from bom_intelligence.profiler.powerpoint import PowerPointProfile, profile_powerpoint

__all__ = [
    "ExcelProfile",
    "KeywordHit",
    "PowerPointProfile",
    "ReadError",
    "profile_excel",
    "profile_powerpoint",
]
