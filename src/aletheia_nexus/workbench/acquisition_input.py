"""Explicit, local-only assignments for pasted acquisition lists.

Classification comes only from user-written headings/fields. No bibliographic
lookup, scientific classification, filename sanitization or filesystem writes
belong in this parser.
"""

from __future__ import annotations

import re
from dataclasses import asdict

from aletheia_nexus.core.identifiers.doi import normalize_doi
from aletheia_nexus.core.organization import normalize_folder

_MARKDOWN = re.compile(r"^(#{2,3})\s+(.+)$")
_BRACKET = re.compile(r"^\[([^\[\]]+)\]$")
_LETTER = re.compile(r"^[A-Z][.．、)]\s*(.+)$")
_NUMBER = re.compile(r"^(?:\d+[.．、)]|[（(]\d+[）)])\s*(.+)$")
_FIELD = re.compile(r"^([^=＝:：]+)\s*[=＝:：](.*)$")
_KEYS = {
    "分类": "folder",
    "文件夹": "folder",
    "folder": "folder",
    "标签": "tags",
    "tags": "tags",
}


def is_bracket_group(line: str) -> bool:
    """Distinguish an explicit bracket heading from auto-detected JSON."""
    return (
        _BRACKET.fullmatch(re.split(r"[|\t]", line, maxsplit=1)[0].strip()) is not None
    )


def _folder(value: str) -> tuple[str | None, str]:
    value = value.strip()
    if value in {"/", "根目录", "文库根目录"}:
        return None, "root"
    if not value:
        raise ValueError("分类不能为空；继承请省略该字段，移到文库根目录请写“分类=/”。")
    try:
        return normalize_folder(value), "custom"
    except ValueError as exc:
        raise ValueError(
            "分类必须是安全的相对目录，不能含绝对路径、上级目录、非法字符或保留名称。"
        ) from exc


def _tags(value: str) -> tuple[str, ...]:
    value = value.strip()
    if value in {"", "[]", "空", "无标签"}:
        return ()
    result = tuple(
        dict.fromkeys(v.strip() for v in re.split(r"[,，;；]", value) if v.strip())
    )
    if any(len(v) > 80 or any(ord(c) < 32 for c in v) for v in result):
        raise ValueError("每个标签需为不含控制字符的文本，长度不超过80个字符。")
    return result


def _metadata(parts: list[str]) -> dict:
    result = {}
    for part in parts:
        if not part.strip():
            continue
        match = _FIELD.fullmatch(part.strip())
        key = _KEYS.get(match[1].strip().casefold()) if match else None
        if key is None:
            raise ValueError(
                "无法识别行内字段；请使用“分类=相对目录”或“标签=标签1,标签2”。"
            )
        if key in result:
            raise ValueError("同一行重复设置了分类或标签，请保留一个明确值。")
        result[key] = match[2].strip()
    return result


def _apply(base: dict, metadata: dict) -> dict:
    result = dict(base)
    if "folder" in metadata:
        result["folder"], result["folder_mode"] = _folder(metadata["folder"])
    if "tags" in metadata:
        result["tags"], result["tags_mode"] = _tags(metadata["tags"]), "custom"
    return result


def _citations(text: str) -> list[dict]:
    """Recognize only a whole DOI/list, never pluck a DOI from citation prose."""

    def all_dois(value):
        # Semicolons can belong to a DOI; treat one as a separator only when
        # followed by another explicit DOI prefix, not for ordinary suffixes.
        value = re.sub(
            r"([;；])(?=(?:https?://(?:dx\.)?doi\.org/)?10\.\d{4,9}/)",
            r"\1 ",
            value,
            flags=re.I,
        )
        try:
            return [normalize_doi(value)]
        except (TypeError, ValueError):
            tokens = [v for v in re.split(r"[\s,，;；|]+", value) if v]
            if len(tokens) < 2:
                return None
            try:
                return [normalize_doi(v) for v in tokens]
            except (TypeError, ValueError):
                return None

    dois = all_dois(text)
    if dois:
        return [{"doi": doi} for doi in dois]
    numbered = _NUMBER.fullmatch(text)
    if numbered:
        dois = all_dois(numbered[1])
        if dois:
            return [{"doi": doi} for doi in dois]
        if re.match(
            r"(?:doi\s*[:：]|(?:https?://)?(?:dx\.)?doi\.org/|10\.\d{4,9}/)",
            numbered[1],
            re.I,
        ):
            raise ValueError(
                "编号后的DOI格式无效，请核对完整DOI；它不会被当作论文标题。"
            )
    if re.match(
        r"(?:doi\s*[:：]|(?:https?://)?(?:dx\.)?doi\.org/|10\.\d{4,9}/)", text, re.I
    ):
        raise ValueError(
            "这一行包含无法识别的DOI内容；逐篇设置请使用“| 分类=...”和“| 标签=...”。"
        )
    return [{"title": text}]


def parse_text_input(text: str) -> dict:
    """Parse explicit groups and named per-paper overrides, retaining line numbers.

    ``## Parent`` / ``### Child`` are hierarchical. Letter and bracket groups
    start a new top-level assignment. A bad heading poisons its group until a
    new valid heading, preventing accidental fallback to the preceding group.
    """
    empty = {
        "folder": None,
        "folder_mode": "inherit",
        "tags": (),
        "tags_mode": "inherit",
    }
    current, parent = dict(empty), None
    parent_error, scope = False, None
    group, group_error = None, None
    entries, errors = [], []
    for line_number, original in enumerate(text.lstrip("\ufeff").splitlines(), 1):
        line = original.strip()
        if not line:
            continue
        parts = [p.strip() for p in re.split(r"[|\t]", line)]
        primary = parts[0]
        markdown = _MARKDOWN.fullmatch(primary)
        bracket = _BRACKET.fullmatch(primary)
        letter = _LETTER.fullmatch(primary)
        # A wrapped DOI is still a DOI, rather than a bracket category.
        try:
            normalize_doi(primary)
            bracket = None
        except ValueError:
            pass
        heading = markdown or bracket or letter
        if heading:
            group = markdown[2] if markdown else heading[1]
            if not markdown:
                # Even a malformed new top-level group ends the old markdown
                # hierarchy; a later child must never reuse that old parent.
                parent, parent_error = None, False
            try:
                base = dict(empty)
                if markdown and markdown[1] == "###" and parent_error:
                    raise ValueError(
                        "上级分类组无效，此子分类未分配论文；请先修改“##”上级组标题。"
                    )
                if markdown and markdown[1] == "###" and parent:
                    base = dict(parent)
                    name, mode = _folder(group)
                    if mode == "root":
                        raise ValueError("子分类不能写根目录；请用独立“分类=/”覆盖。")
                    if parent["folder"]:
                        group_folder = parent["folder"] + "/" + name
                    else:
                        group_folder = name
                    base["folder"], base["folder_mode"] = _folder(group_folder)
                else:
                    base["folder"], base["folder_mode"] = _folder(group)
                current = _apply(base, _metadata(parts[1:]))
                group_error = None
                if markdown and markdown[1] == "##":
                    parent = dict(current)
                    parent_error, scope = False, "parent"
                elif markdown:
                    scope = "child"
                elif not markdown:
                    parent, parent_error, scope = None, False, "top"
            except ValueError as exc:
                group_error = str(exc)
                # An invalid markdown parent must never inherit the last parent.
                if markdown and markdown[1] == "##":
                    parent, parent_error = None, True
                errors.append(
                    {"line": line_number, "error": group_error, "input": line}
                )
            continue
        field_match = _FIELD.fullmatch(primary)
        if field_match and field_match[1].strip().casefold() in _KEYS:
            try:
                if group_error:
                    raise ValueError(
                        "当前分类组无效，请先修改组标题或开始一个合法新组。"
                    )
                current = _apply(current, _metadata(parts))
                if scope == "parent":
                    parent = dict(current)
            except ValueError as exc:
                group_error = str(exc)
                if scope == "parent":
                    parent, parent_error = None, True
                errors.append(
                    {"line": line_number, "error": group_error, "input": line}
                )
            continue
        try:
            if group_error:
                raise ValueError("当前分类组无效，此项未使用前一组分类；请修改组标题。")
            has_metadata = len(parts) > 1 and any(
                _FIELD.fullmatch(p) for p in parts[1:] if p
            )
            settings = (
                _apply(current, _metadata(parts[1:])) if has_metadata else dict(current)
            )
            citations = _citations(primary if has_metadata else line)
            for citation in citations:
                entries.append(
                    {
                        "value": {
                            **citation,
                            "folder": settings["folder"],
                            "tags": settings["tags"],
                        },
                        "line": line_number,
                        "group": group,
                        "assignment": {
                            "folder_mode": settings["folder_mode"],
                            "tags_mode": settings["tags_mode"],
                        },
                    }
                )
        except ValueError as exc:
            errors.append({"line": line_number, "error": str(exc), "input": line})
    return {"entries": entries, "errors": errors, "warnings": []}


def structured_entries(rows) -> list[dict]:
    """Keep existing CSV/JSON fields; blank organization still means inherit."""
    return [
        {"value": row, "line": number, "group": None}
        for number, row in enumerate(rows, 1)
    ]


def build_input_preview(
    entries, *, normalizer, folder_check, errors=(), warnings=()
) -> dict:
    """Retain conflicting alternatives instead of deduplicating their assignments."""
    items, errors, warnings = [], list(errors), list(warnings)
    identity_rows, signatures, key_counts = {}, {}, {}
    for entry in entries:
        line = entry["line"]
        try:
            request = normalizer(entry["value"])
            folder_check(request.folder)
            assignment = entry.get("assignment") or {
                "folder_mode": "custom" if request.folder else "inherit",
                "tags_mode": "custom" if request.tags else "inherit",
            }
            identity = "doi:" + request.doi if request.doi else request.key
            signature = (
                request.key,
                request.folder,
                tuple(sorted(request.tags)),
                request.filename,
                assignment["folder_mode"],
                assignment["tags_mode"],
            )
            original = signatures.get(signature)
            occurrence = key_counts.get(request.key, 0)
            key_counts[request.key] = occurrence + 1
            item_id = (
                request.key
                if not occurrence
                else f"{request.key}:input:{len(items) + 1}"
            )
            item = {
                "id": item_id,
                "paper_key": request.key,
                "identity": identity,
                "request": asdict(request),
                "duplicate": original is not None,
                "conflict": False,
                "line": line,
                "group": entry.get("group"),
                "assignment": dict(assignment),
            }
            items.append(item)
            if original is not None:
                warnings.append(
                    {
                        "code": "DUPLICATE_INPUT",
                        "line": line,
                        "original_line": original["line"],
                        "item_id": item_id,
                        "message": "此项与前面的论文及分类、标签设置完全相同，预览保留记录但不重复获取。",
                    }
                )
            else:
                signatures[signature] = item
                identity_rows.setdefault(identity, []).append(item)
        except (TypeError, ValueError) as exc:
            errors.append({"line": line, "error": str(exc)})
    conflicts = []
    for identity, variants in identity_rows.items():
        if len(variants) < 2:
            continue
        fields = []
        for name in ("folder", "tags", "filename"):
            values = {
                (
                    tuple(sorted(item["request"][name]))
                    if name == "tags"
                    else item["request"][name],
                    item["assignment"].get(name + "_mode"),
                )
                for item in variants
            }
            if len(values) > 1:
                fields.append(name)
        if len({item["paper_key"] for item in variants}) > 1:
            fields.append("bibliography")
        for item in items:
            if item["identity"] == identity:
                item["conflict"] = True
        conflicts.append(
            {
                "code": "CONFLICTING_PAPER_INPUT",
                "identity": identity,
                "item_ids": [item["id"] for item in variants],
                "lines": [item["line"] for item in variants],
                "fields": fields,
                "message": "同一论文存在不同分类、标签、命名或书目约束；请明确保留一个候选，或统一设置后再启动。",
            }
        )
    errors.sort(key=lambda row: row["line"])
    return {
        "items": items,
        "errors": errors,
        "warnings": warnings,
        "conflicts": conflicts,
        "count": sum(not item["duplicate"] for item in items),
        "paper_count": len(identity_rows),
        "ready": not errors and not conflicts,
    }
