"""Composable, request-local parsing pipeline."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from aletheia_nexus.content.models import PipelineContext


class ParserStage(Protocol):
    name: str

    def run(self, context: PipelineContext) -> None: ...


class ParserPipeline:
    """Execute ordered stages and expose their identities for provenance."""

    def __init__(self, stages: Sequence[ParserStage]):
        if not stages:
            raise ValueError("a parser pipeline needs at least one stage")
        names = [stage.name for stage in stages]
        if len(names) != len(set(names)):
            raise ValueError("parser stage names must be unique")
        self._stages = tuple(stages)

    @property
    def stage_names(self) -> tuple[str, ...]:
        return tuple(stage.name for stage in self._stages)

    def run(self, context: PipelineContext) -> None:
        for stage in self._stages:
            stage.run(context)
