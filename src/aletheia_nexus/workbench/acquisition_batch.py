"""Pure, ID-based acquisition placement edits and validated final requests.

Selection determines which rows an edit affects; ``enabled`` independently
determines which papers are submitted. Explicit modes distinguish inheritance,
the library root and intentionally empty tags, before PaperRequest folding.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, fields

from aletheia_nexus.core.organization import normalize_folder
from aletheia_nexus.core.paper_request import PaperRequest

from .acquisition import normalize_request

_FOLDER_MODES = {"inherit", "custom", "root"}
_TAG_MODES = {"inherit", "custom"}
_FOLDER_ACTIONS = {"keep", "inherit", "set", "root"}
_TAG_ACTIONS = {"keep", "inherit", "replace", "add", "remove", "clear"}
_REQUEST_FIELDS = {field.name for field in fields(PaperRequest)} - {"folder", "tags"}


def _identity(value):
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or len(value) > 256
        or any(ord(c) < 32 or ord(c) == 127 for c in value)
    ):
        raise ValueError("每行必须有唯一、非空的稳定文献编号。")
    return value


def _folder(value, *, allow_root=False):
    if value is None or value == "":
        if allow_root:
            return None
        raise ValueError("指定分类不能为空；保存到文库根目录请明确选择“文库根目录”。")
    try:
        result = normalize_folder(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "分类须为安全的相对目录，不得包含绝对路径、上级目录、非法字符或保留目录名。"
        ) from exc
    if result is None:
        raise ValueError("指定分类不能为空；保存到文库根目录请明确选择“文库根目录”。")
    return result


def _tags(value):
    if isinstance(value, str):
        if any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("标签不能包含换行或其他控制字符。")
        parts = [s.strip() for s in value.replace("，", ",").split(",") if s.strip()]
    elif isinstance(value, (list, tuple)):
        parts = list(value)
    else:
        raise ValueError("标签须为逗号分隔的文字或文字列表。")
    if any(
        not isinstance(t, str)
        or not t.strip()
        or len(t.strip()) > 80
        or any(ord(c) < 32 or ord(c) == 127 for c in t)
        or "," in t
        or "，" in t
        for t in parts
    ):
        raise ValueError("每个标签须为最多80字的非空文字，不能包含逗号或控制字符。")
    return list(dict.fromkeys(t.strip() for t in parts))


def _rows(rows):
    if not isinstance(rows, (list, tuple)):
        raise ValueError("获取候选须为完整的文献行列表。")
    result, seen = deepcopy(list(rows)), set()
    for row in result:
        if not isinstance(row, dict):
            raise ValueError("每个获取候选必须是一组命名字段。")
        paper_id = _identity(row.get("id"))
        if paper_id in seen:
            raise ValueError("获取候选包含重复稳定编号，不能确定要修改的论文。")
        seen.add(paper_id)
        if type(row.get("enabled")) is not bool:
            raise ValueError("每篇论文的获取开关必须明确为开启或关闭。")
        if (
            not isinstance(row.get("folder_mode"), str)
            or row["folder_mode"] not in _FOLDER_MODES
        ):
            raise ValueError("分类方式须为继承默认、指定分类或文库根目录。")
        if (
            not isinstance(row.get("tags_mode"), str)
            or row["tags_mode"] not in _TAG_MODES
        ):
            raise ValueError("标签方式须为继承默认或单篇自定义。")
        if row["folder_mode"] == "custom":
            _folder(row.get("folder"))
        if row["tags_mode"] == "custom":
            _tags(row.get("tags"))
    return result, seen


def _effective(row, default_folder, default_tags):
    folder = (
        default_folder
        if row["folder_mode"] == "inherit"
        else None
        if row["folder_mode"] == "root"
        else _folder(row.get("folder"))
    )
    tags = default_tags if row["tags_mode"] == "inherit" else _tags(row.get("tags"))
    return folder, list(tags)


def apply_assignment(
    rows,
    selected_ids,
    *,
    folder_action="keep",
    folder="",
    tag_action="keep",
    tags=(),
    default_folder=None,
    default_tags=(),
):
    """Return all rows after an atomic, strictly ID-based local assignment edit.

    All validation precedes changes, and caller-owned rows/defaults are never
    mutated. Add/remove starts from each row's effective tags and materializes a
    custom value. Empty add/remove is a no-op; clear always writes custom empty.
    """
    result, known = _rows(rows)
    if not isinstance(selected_ids, (list, tuple, set, frozenset)):
        raise ValueError("请按稳定文献编号传入需要编辑的选择清单。")
    selected = [_identity(value) for value in selected_ids]
    if len(set(selected)) != len(selected) or set(selected) - known:
        raise ValueError("选择清单含重复或未知文献编号，请刷新候选后重新选择。")
    if (
        not isinstance(folder_action, str)
        or not isinstance(tag_action, str)
        or folder_action not in _FOLDER_ACTIONS
        or tag_action not in _TAG_ACTIONS
    ):
        raise ValueError("批量分类或标签操作不受支持，请重新选择操作。")
    default_folder = _folder(default_folder, allow_root=True)
    default_tags = _tags(default_tags)
    new_folder = _folder(folder) if folder_action == "set" else None
    changed_tags = _tags(tags)
    selected = set(selected)
    for row in result:
        if row["id"] not in selected:
            continue
        _, effective_tags = _effective(row, default_folder, default_tags)
        if folder_action == "set":
            row.update(folder_mode="custom", folder=new_folder)
        elif folder_action in {"root", "inherit"}:
            row.update(folder_mode=folder_action, folder="")
        if tag_action == "inherit":
            row.update(tags_mode="inherit", tags="")
        elif tag_action in {"replace", "clear"}:
            row.update(
                tags_mode="custom",
                tags=", ".join(changed_tags) if tag_action == "replace" else "",
            )
        elif tag_action in {"add", "remove"} and changed_tags:
            effective_tags = (
                list(dict.fromkeys([*effective_tags, *changed_tags]))
                if tag_action == "add"
                else [tag for tag in effective_tags if tag not in changed_tags]
            )
            row.update(tags_mode="custom", tags=", ".join(effective_tags))
    return result


def build_requests(rows, original_request_map, default_folder=None, default_tags=()):
    """Fold explicit placement modes into real, normalized PaperRequest dicts.

    The server-owned map must contain exactly all displayed row IDs. Disabled
    rows stay outside the submission. Repeated enabled DOI/CNKI/bibliographic
    identities are rejected so different placements cannot be silently dropped.
    """
    rows, known = _rows(rows)
    if not isinstance(original_request_map, dict) or set(original_request_map) != known:
        raise ValueError("原始文献与候选行编号不一致，请重新生成完整预览。")
    default_folder = _folder(default_folder, allow_root=True)
    default_tags = _tags(default_tags)
    requests, identities = [], {}
    for row in rows:
        if not row["enabled"]:
            continue
        paper_id = row["id"]
        try:
            original = asdict(normalize_request(original_request_map[paper_id]))
            payload = {
                **original,
                **{key: row[key] for key in _REQUEST_FIELDS if key in row},
            }
            payload["folder"], payload["tags"] = _effective(
                row, default_folder, default_tags
            )
            request = normalize_request(payload)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"文献 {paper_id} 的获取参数无效，请核对DOI、标题、年份、作者和文件基础名称。"
            ) from exc
        keys = []
        if request.doi:
            keys.append(("doi", request.doi))
        if request.cnki_id:
            keys.append(("cnki", request.cnki_id))
        keys = keys or [("bibliographic", request.key)]
        for key in keys:
            if key in identities:
                other_id, other = identities[key]
                placement_conflict = (
                    request.folder != other.folder
                    or request.filename != other.filename
                    or set(request.tags) != set(other.tags)
                )
                detail = "，且分类、文件名或标签存在冲突" if placement_conflict else ""
                raise ValueError(
                    f"文献 {other_id} 与 {paper_id} 重复启用同一论文身份{detail}；"
                    "请保留一个获取行并确认分类和标签，系统不会静默选择首条。"
                )
            identities[key] = paper_id, request
        normalized = asdict(request)
        normalized["authors"] = list(request.authors)
        normalized["tags"] = list(request.tags)
        requests.append(normalized)
    if not requests:
        raise ValueError("没有启用获取的论文，请开启至少一篇论文的获取开关。")
    return requests
