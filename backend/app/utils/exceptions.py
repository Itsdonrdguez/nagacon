class IngestionError(Exception):
    """Base error for ingestion issues."""


class NormalizationError(IngestionError):
    """Raised when a raw record cannot be normalized."""


class DuplicateRecordError(IngestionError):
    """Raised when a duplicate cannot be resolved safely."""
