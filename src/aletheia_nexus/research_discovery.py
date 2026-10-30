"""One public title-to-candidates plan, shared by local grants and MCP."""

from aletheia_nexus.acquire.metadata.crossref import CROSSREF_API, normalize_title_query


def title_discovery_plan(payload: dict) -> dict:
    if not isinstance(payload, dict) or payload.keys() - {"title_query", "limit"}:
        raise ValueError("discovery accepts title_query and optional limit only")
    query, limit = normalize_title_query(
        payload.get("title_query"), payload.get("limit", 5)
    )
    normalized = {"title_query": query, "limit": limit}
    return {
        "payload": normalized,
        "binding": {
            "version": "crossref-title-discovery/1",
            "endpoint": CROSSREF_API + "/works",
            **normalized,
        },
        "plan": (
            f"查询书目候选：{query}\n"
            f"公共服务：{CROSSREF_API}/works；最多{limit}个候选、1次元数据请求。\n"
            "只发送上述查询文字，不发送论文或本地文件，不调用模型，不下载论文。\n"
            "候选不是身份确认；选择DOI后，全文获取仍需独立acquire授权。"
        ),
    }
