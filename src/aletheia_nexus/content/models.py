"""Typed intermediate representation shared by parser backends and stages."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class LayoutLine:
    """One positioned native-text line before semantic block assembly."""

    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    font_size: float
    extraction_method: str = "pypdf-content-stream"
    uncertain: bool = False


@dataclass(frozen=True)
class PageObject:
    """A non-text PDF object that can be linked without extracting its bytes."""

    object_type: str
    name: str
    width: int | None = None
    height: int | None = None
    bbox: tuple[float, float, float, float] | None = None


@dataclass(frozen=True)
class PageLayout:
    """Backend-neutral page output consumed by parser stages."""

    page: int
    width: float
    height: float
    lines: tuple[LayoutLine, ...] = ()
    objects: tuple[PageObject, ...] = ()
    warnings: tuple[dict[str, str], ...] = ()


@dataclass
class PipelineContext:
    """Mutable per-request state; no state is shared between parser runs."""

    source: object
    reader: object
    config: object
    created_at: str
    backend: object
    layouts: dict[int, PageLayout] = field(default_factory=dict)
    blocks: list[dict[str, object]] = field(default_factory=list)
    anchors: list[dict[str, object]] = field(default_factory=list)
    sections: list[dict[str, object]] = field(default_factory=list)
    references: list[dict[str, object]] = field(default_factory=list)
    figures: list[dict[str, object]] = field(default_factory=list)
    tables: list[dict[str, object]] = field(default_factory=list)
    quality: dict[str, object] = field(default_factory=dict)
    status: str = "FAILED"
    warnings: list[dict[str, str]] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)
    stopped_early: bool = False
