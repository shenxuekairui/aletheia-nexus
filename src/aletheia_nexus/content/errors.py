"""Typed failures for the parsing trust boundary."""

from enum import Enum


class ParserInputErrorCode(str, Enum):
    PDF_NOT_FOUND = "PDF_NOT_FOUND"
    SIDECAR_NOT_FOUND = "SIDECAR_NOT_FOUND"
    UNVERIFIED_PATH = "UNVERIFIED_PATH"
    INVALID_SIDECAR = "INVALID_SIDECAR"
    UNKNOWN_SIDECAR_SCHEMA = "UNKNOWN_SIDECAR_SCHEMA"
    STATUS_NOT_VERIFIED = "STATUS_NOT_VERIFIED"
    PDF_VALIDATION_FAILED = "PDF_VALIDATION_FAILED"
    IDENTITY_NOT_MATCHED = "IDENTITY_NOT_MATCHED"
    DOCUMENT_NOT_ARTICLE = "DOCUMENT_NOT_ARTICLE"
    DOI_MISMATCH = "DOI_MISMATCH"
    INVALID_RECORDED_HASH = "INVALID_RECORDED_HASH"
    PDF_HASH_MISMATCH = "PDF_HASH_MISMATCH"
    SIDECAR_CHANGED = "SIDECAR_CHANGED"
    PDF_UNREADABLE = "PDF_UNREADABLE"
    PAGE_COUNT_MISMATCH = "PAGE_COUNT_MISMATCH"


class ParserInputError(ValueError):
    """A fail-closed parser input error with a stable machine-readable code."""

    def __init__(self, code: ParserInputErrorCode, detail: str):
        self.code = code
        self.detail = detail
        super().__init__(f"{code.value}: {detail}")
