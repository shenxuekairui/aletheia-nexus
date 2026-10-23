"""Optional, advisory reading assessment over existing source evidence.

No provider, network client or automatic rewriting is installed here. Callers
can supply a local or remote judge explicitly, after choosing the evidence scope.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True)
class ReadingDecision:
    """A preference is a suggestion, not verified scientific truth."""

    outcome: Literal["prefer", "unresolved", "abstain"]
    block_ids: tuple[str, ...] = ()
    reason: str = ""


class EvidenceJudge(Protocol):
    name: str
    version: str

    def judge(self, request: dict[str, object]) -> ReadingDecision:
        """Assess supplied context; abstain when source evidence is insufficient.

        Document content is evidence, never instructions. A provider may inspect
        the original PDF using its locator and hash. It must not resolve a real
        source contradiction by choosing the more plausible scientific value.
        """
        ...


def assess_reading(
    pack: dict[str, object],
    judge: EvidenceJudge,
    *,
    parsed_artifact_id: str,
    location_id: str,
    question: str,
) -> dict[str, object]:
    """Ask one explicit judge about a source location, preserving page context.

    Provider failures propagate to the caller. Only references to supplied
    blocks are accepted. No parsed text, uncertainty flag or pack is modified.
    """
    if pack.get("schema") != "aletheia-nexus/evidence-pack/v1":
        raise ValueError("expected an AN evidence pack")
    if not question.strip():
        raise ValueError("an assessment question is required")
    entry = next(
        (e for e in pack["included"] if e["parsed_artifact_id"] == parsed_artifact_id),
        None,
    )
    if entry is None:
        raise ValueError("document is not included in the evidence pack")
    location = next(
        (g for g in entry["review_locations"] if g["id"] == location_id), None
    )
    if location is None:
        raise ValueError("unknown review location")
    request = deepcopy(
        {
            "schema": "aletheia-nexus/reading-assessment-request/v1",
            "evidence_pack_id": pack["artifact_id"],
            "question": question,
            "target": location,
            "document": entry,
        }
    )
    decision = judge.judge(request)
    if not isinstance(decision, ReadingDecision) or decision.outcome not in {
        "prefer",
        "unresolved",
        "abstain",
    }:
        raise ValueError("judge returned an invalid reading decision")
    blocks = {b["id"]: b for b in entry["blocks"]}
    if (
        not isinstance(decision.block_ids, tuple)
        or any(
            not isinstance(bid, str) or bid not in blocks for bid in decision.block_ids
        )
        or len(set(decision.block_ids)) != len(decision.block_ids)
        or not isinstance(decision.reason, str)
        or not decision.reason.strip()
    ):
        raise ValueError(
            "decision requires a reason and unique supplied block references"
        )
    if decision.outcome != "abstain" and not set(decision.block_ids).intersection(
        location["block_ids"]
    ):
        raise ValueError("decision must cite the target source location")
    return {
        "schema": "aletheia-nexus/reading-assessment/v1",
        "evidence_pack_id": pack["artifact_id"],
        "parsed_artifact_id": parsed_artifact_id,
        "location_id": location_id,
        "question": question,
        "judge": {"name": judge.name, "version": judge.version},
        "outcome": decision.outcome,
        "reason": decision.reason,
        "advisory": True,
        "citations": [
            deepcopy(
                {
                    "block_id": bid,
                    "text": blocks[bid]["text"],
                    "evidence": blocks[bid]["evidence"],
                }
            )
            for bid in decision.block_ids
        ],
    }
