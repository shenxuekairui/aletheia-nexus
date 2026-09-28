"""Source-linked scientific-document parsing.

The content layer accepts only immutable, verified acquisition artifacts.  It
does not perform acquisition and it does not assess the truth of paper claims.
"""

from aletheia_nexus.content.artifact import (
    ParsedArtifact,
    SearchHit,
    load_parsed_document,
)
from aletheia_nexus.content.backends import (
    AdaptiveOcrBackend,
    AdaptiveOcrConfig,
    ExtractionBackend,
    NativePdfBackend,
    RegionExtractionBackend,
    TesseractOcrBackend,
    TesseractOcrConfig,
)
from aletheia_nexus.content.errors import ParserInputError, ParserInputErrorCode
from aletheia_nexus.content.export import (
    AI_EXPORT_SCHEMA,
    ChunkConfig,
    export_jsonl,
    export_markdown,
    serialize_chunks,
    structure_aware_chunks,
    write_ai_export,
)
from aletheia_nexus.content.gate import ParserInput, validate_parser_input
from aletheia_nexus.content.parser import ParserConfig
from aletheia_nexus.content.schema import (
    PARSED_DOCUMENT_SCHEMA,
    serialize_parsed_document,
    validate_parsed_document,
)
from aletheia_nexus.content.service import ParseResult, parse_document

__all__ = [
    "ParseResult",
    "AdaptiveOcrBackend",
    "AdaptiveOcrConfig",
    "ExtractionBackend",
    "NativePdfBackend",
    "RegionExtractionBackend",
    "TesseractOcrBackend",
    "TesseractOcrConfig",
    "ParsedArtifact",
    "ParserConfig",
    "ParserInput",
    "ParserInputError",
    "ParserInputErrorCode",
    "SearchHit",
    "PARSED_DOCUMENT_SCHEMA",
    "parse_document",
    "load_parsed_document",
    "serialize_parsed_document",
    "validate_parsed_document",
    "validate_parser_input",
    "AI_EXPORT_SCHEMA",
    "ChunkConfig",
    "export_jsonl",
    "export_markdown",
    "serialize_chunks",
    "structure_aware_chunks",
    "write_ai_export",
]
