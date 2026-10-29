"""Bounded closing-only JSON recovery; parsing and schema checks remain native."""

from __future__ import annotations

import hashlib
import json
from typing import Callable

VERSION = "closing-only-json/1"
MAX_BYTES = 64 * 1024
MAX_POSITIONS = 4096
MAX_EOF_CLOSINGS = 2


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _positions(raw: str):
    positions, stack = [], []
    quoted = escaped = mismatch = False
    for index, char in enumerate(raw):
        if not quoted:
            positions.append(index)
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "{[":
            stack.append(char)
        elif char in "}]":
            if stack and stack[-1] == ("{" if char == "}" else "["):
                stack.pop()
            else:
                mismatch = True
    if not quoted:
        positions.append(len(raw))
    suffix = (
        ""
        if quoted or mismatch
        else "".join("}" if c == "{" else "]" for c in reversed(stack))
    )
    return positions, suffix


def _fingerprint(value) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


def apply_closure(raw: str, insertion: dict) -> str:
    position, characters = insertion["position"], insertion["characters"]
    return raw[:position] + characters + raw[position:]


def recover_closure(raw: str, project: Callable[[dict], dict]) -> tuple[dict, dict]:
    """One outside-string closing OR <=2 EOF closings, one canonical response only.

    Called only after JSONDecodeError on a completed response, or for deterministic
    replay of its metadata. No strings, numeric literals, keys, commas or values
    are supplied or rewritten. Duplicate keys cannot discard original values.
    """
    if len(raw.encode()) > MAX_BYTES:
        raise ValueError("json_closure: raw resource limit")
    positions, suffix = _positions(raw)
    if len(positions) > MAX_POSITIONS:
        raise ValueError("json_closure: position resource limit")
    insertions = [
        {"position": p, "characters": c} for p in positions for c in ("}", "]")
    ]
    if 1 <= len(suffix) <= MAX_EOF_CLOSINGS:
        insertions.append({"position": len(raw), "characters": suffix})
    seen, interpretations = set(), {}
    for insertion in insertions:
        fixed = apply_closure(raw, insertion)
        fixed_hash = hashlib.sha256(fixed.encode()).hexdigest()
        if fixed_hash in seen:
            continue
        seen.add(fixed_hash)
        try:
            parsed = json.loads(fixed, object_pairs_hook=_unique_object)
            canonical = project(parsed)
            identity = _fingerprint(canonical)
        except (ValueError, TypeError, KeyError, AttributeError):
            continue
        candidate = {"insertion": insertion, "closed_raw_sha256": fixed_hash}
        if identity not in interpretations:
            interpretations[identity] = {"parsed": parsed, "candidates": []}
        interpretations[identity]["candidates"].append(candidate)
    if not interpretations:
        raise ValueError("json_closure: no complete schema interpretation")
    if len(interpretations) != 1:
        raise ValueError("json_closure: ambiguous schema interpretations")
    identity, only = next(iter(interpretations.items()))
    return only["parsed"], {
        "version": VERSION,
        "completed_response": True,
        "raw_sha256": hashlib.sha256(raw.encode()).hexdigest(),
        "canonical_sha256": identity,
        "selected": only["candidates"][0],
        "equivalent_candidates": only["candidates"],
    }
