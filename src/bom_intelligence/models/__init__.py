"""Canonical domain models."""

from bom_intelligence.models.bom import (
    SCHEMA_VERSION,
    BOMRecord,
    CostInfo,
    CostType,
    ExtractionEvidence,
    ExtractionMetadata,
    ExtractionMethod,
    MilestoneType,
    PartIdentity,
    ScheduleInfo,
    SourceReference,
)
from bom_intelligence.models.diagnostics import (
    FAILURE_CODE_INFO,
    Diagnostic,
    FailureCode,
    FailureGroup,
    Location,
    Observation,
    Severity,
    SuggestedStrategy,
    failure_group,
)
from bom_intelligence.models.document import DocumentType, document_type_for_suffix

__all__ = [
    "FAILURE_CODE_INFO",
    "SCHEMA_VERSION",
    "BOMRecord",
    "CostInfo",
    "CostType",
    "Diagnostic",
    "DocumentType",
    "ExtractionEvidence",
    "ExtractionMetadata",
    "ExtractionMethod",
    "FailureCode",
    "FailureGroup",
    "Location",
    "MilestoneType",
    "Observation",
    "PartIdentity",
    "ScheduleInfo",
    "Severity",
    "SourceReference",
    "SuggestedStrategy",
    "document_type_for_suffix",
    "failure_group",
]
