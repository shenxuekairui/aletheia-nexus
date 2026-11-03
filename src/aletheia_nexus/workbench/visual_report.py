"""Offline, escaped HTML presentation of existing native research results."""

from __future__ import annotations

import base64
import html
import json
import re
from datetime import datetime
from pathlib import Path

from .labels import value_label


def esc(value):
    return html.escape(str(value if value is not None else ""), quote=True)


def paragraphs(value):
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False)
    parts = re.split(r"\n+|(?<=。)(?=.{50})", value)
    return "".join(f"<p>{esc(part)}</p>" for part in parts if part.strip())


CSS = """
:root{--ink:#183245;--muted:#617586;--teal:#087f83;--line:#dce6eb;--paper:#fff}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:#f0f5f7;color:var(--ink);font:16px/1.85 'Microsoft YaHei','PingFang SC',sans-serif}
a{color:var(--teal);text-underline-offset:4px}header{background:#143e50;color:white;padding:55px max(6vw,24px) 38px}header h1{max-width:1050px;font-size:clamp(26px,3vw,40px);line-height:1.45;margin:10px 0 20px}header p{color:#c9e1e7;margin:0}.eyebrow{font-size:12px;letter-spacing:3px;color:#8cd0cf}.chips{display:flex;flex-wrap:wrap;gap:10px;margin-top:24px}.chip{padding:4px 14px;border:1px solid #4c7380;border-radius:24px;font-size:13px}
.layout{max-width:1400px;margin:auto;display:grid;grid-template-columns:210px minmax(0,1fr);gap:32px;padding:32px 28px}nav{position:sticky;top:24px;align-self:start}nav a{display:block;text-decoration:none;padding:8px 12px;border-left:2px solid var(--line);font-size:14px}nav a:hover{background:white;border-color:var(--teal)}main{min-width:0}section{margin:0 0 26px;background:var(--paper);border:1px solid var(--line);border-radius:14px;padding:30px;scroll-margin-top:20px}h2{margin:0 0 22px;font-size:24px}h3{margin:0 0 12px;font-size:19px}p{margin:0 0 14px}.muted{color:var(--muted);font-size:13px}.notice{background:#fff8e8;border-left:4px solid #b88624;padding:16px 20px;margin-bottom:26px;border-radius:6px}.notice p:last-child{margin:0}.cards{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}.card{border:1px solid var(--line);border-radius:10px;padding:20px}.card-number{font-size:12px;letter-spacing:2px;color:var(--teal);margin-bottom:10px}.field{border-top:1px solid var(--line);padding-top:24px;margin-top:24px}.field:first-of-type{border-top:0;padding-top:0}.context{background:#f0f7f7;padding:12px 16px;color:#506c73;font-size:14px;border-radius:6px}.references{display:flex;gap:7px;flex-wrap:wrap;margin-top:12px}.references a{background:#edf5f6;border-radius:4px;padding:1px 8px;font-size:12px;text-decoration:none}.issue{padding:15px 18px;background:#fff8e8;border-radius:6px;margin:12px 0}.request{border:1px solid #e6d7b7;padding:18px;border-radius:8px;margin:14px 0}.gallery{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}.gallery details{border:1px solid var(--line);border-radius:8px;overflow:hidden}.gallery summary{padding:12px 16px;cursor:pointer;background:#f5f9fa}.gallery img{display:block;width:100%;height:auto}.gallery details[open]{grid-column:1/-1}.ref{border-top:1px solid var(--line);padding:14px 0;scroll-margin-top:20px}.ref summary{cursor:pointer;font-size:14px}.ref blockquote{margin:12px 0 0;padding:12px 16px;background:#f5f8fa;border-left:3px solid #b4d6d6;font-size:14px}table{width:100%;border-collapse:collapse;font-size:14px}th,td{text-align:left;vertical-align:top;padding:10px;border-bottom:1px solid var(--line);overflow-wrap:anywhere}th{width:130px;color:var(--muted);font-weight:normal}.toolbar{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:20px}button{border:0;border-radius:6px;background:var(--teal);color:white;padding:11px 20px;cursor:pointer;font:inherit;font-size:14px}footer{padding:24px;text-align:center;color:var(--muted);font-size:13px}.hash{font-family:monospace;font-size:12px;overflow-wrap:anywhere}
@media(max-width:850px){.layout{grid-template-columns:1fr;padding:18px 14px;gap:16px}nav{position:static;display:flex;flex-wrap:wrap}nav a{padding:5px 10px}section{padding:22px}.cards,.gallery{grid-template-columns:1fr}header{padding:34px 22px}}
@media print{body{background:white;font-size:11pt}header{background:white;color:var(--ink);padding:15px}header p,.eyebrow{color:var(--muted)}.layout{display:block;padding:0}.toolbar,nav{display:none}section{border:0;padding:14px 0;border-radius:0}h2,h3{break-after:avoid}.card,.issue,.request{break-inside:avoid}.cards{display:block}.card{margin-bottom:12px}.chip{border-color:#aaa}.gallery{display:block}.gallery details{margin-bottom:15px}footer{font-size:9pt}}
"""


def write_visual_report(results, output: Path, *, page_images=None):
    """Present every native field/claim/issue; no inference or provider calls.

    page_images is populated by the caller only after source hash/path checks.
    Missing source PDFs never prevent historical result text from being read.
    """
    page_images = page_images or {}
    refs, ref_index = [], {}

    def citations(items, result):
        links = []
        for item in items or []:
            key = (
                result["artifact_id"],
                item.get("source_id"),
                item.get("page"),
                item.get("block_id"),
                item.get("quote"),
            )
            if key not in ref_index:
                ref_index[key] = len(refs) + 1
                refs.append((item, result["artifact_id"]))
            number = ref_index[key]
            links.append(
                f'<a href="#ref-{number}">[{number}] 原文 p.{esc(item.get("page", "?"))}</a>'
            )
        return '<div class="references">' + "".join(links) + "</div>"

    titles = list(
        dict.fromkeys(
            d["source"].get("title") or d["id"]
            for r in results
            for d in r["package"]["documents"]
        )
    )
    title = " / ".join(titles)
    claims = sum(len(r["response"].get("claims", [])) for r in results)
    field_count = sum(
        len(rec.get("fields", {}))
        for r in results
        for rec in r["response"].get("records", [])
    )
    models = ", ".join(
        dict.fromkeys(r["provider"].get("model", "未记录") for r in results)
    )
    sources = {
        (r["artifact_id"], d["id"]): d
        for r in results
        for d in r["package"]["documents"]
    }
    total_pages = sum(len(d.get("pages_requested", [])) for d in sources.values())
    sections = []
    cards = []
    for r in results:
        for claim in r["response"].get("claims", []):
            cards.append(
                f'<article class="card"><div class="card-number">结论 {len(cards) + 1:02d} · 请结合核对记录阅读</div>{paragraphs(claim.get("text", ""))}{citations(claim.get("citations"), r)}</article>'
            )
    sections.append(
        '<section id="overview"><h2>主要结论</h2><div class="cards">'
        + "".join(cards)
        + "</div></section>"
    )
    content = []
    for r in results:
        labels = {f["id"]: f.get("label") or f["id"] for f in r["task"]["fields"]}
        for record in r["response"].get("records", []):
            content.append(f"<h3>{esc(record.get('subject', '研究记录'))}</h3>")
            for key, field in record.get("fields", {}).items():
                unit = f" · 单位：{esc(field['unit'])}" if field.get("unit") else ""
                context = (
                    f'<div class="context">{esc(field["context"])}</div>'
                    if field.get("context")
                    else ""
                )
                content.append(
                    f'<article class="field"><h3>{esc(labels.get(key, key))}</h3><p class="muted">核对状态：{esc(value_label(r.get("validation", {}).get("record_states", {}).get(record.get("id"), "未确认")))}{unit}</p>{paragraphs(field.get("value"))}{context}{citations(field.get("citations"), r)}</article>'
                )
            if record.get("steps"):
                content.append("<h3>步骤记录</h3>" + paragraphs(record["steps"]))
    sections.append(
        '<section id="findings"><h2>完整研究报告</h2>' + "".join(content) + "</section>"
    )
    issues = []
    for r in results:
        for item in r["response"].get("issues", []):
            issues.append(
                '<div class="issue">' + paragraphs(item.get("detail", item)) + "</div>"
            )
        for request in r["response"].get("requests", []):
            pages = "、".join(map(str, request.get("pages", [])))
            issues.append(
                f'<div class="request"><strong>需要进一步核对 · 原文第 {esc(pages)} 页</strong>{paragraphs(request.get("reason", ""))}<p class="muted">未自动补发图片或增加模型调用；下方原页仅供本地查看。</p></div>'
            )
    sections.append(
        '<section id="review"><h2>待核对事项与材料缺口</h2>'
        + ("".join(issues) or "<p>模型未列出材料缺口；这不代表科学结论已经核实。</p>")
        + "</section>"
    )
    gallery = []
    for (result_id, source_id, page), image in page_images.items():
        source_title = sources[(result_id, source_id)]["source"].get("title", source_id)
        encoded = base64.b64encode(image).decode("ascii")
        gallery.append(
            f'<details><summary>{esc(source_title)} · 原文 p.{page} · 点击展开</summary><img loading="lazy" alt="原文第{page}页，未经AI补读" src="data:image/png;base64,{encoded}"></details>'
        )
    sections.append(
        '<section id="original"><h2>原页图表与证据</h2><p class="muted">这些原页直接由本地 PDF 渲染，可离线查看。展示图片不改变模型原来的待核对状态。</p><div class="gallery">'
        + (
            "".join(gallery)
            or "<p>当前没有嵌入原页，可在溯光研究成果中点击引用核对原文。</p>"
        )
        + "</div></section>"
    )
    references = []
    for number, (ref, result_id) in enumerate(refs, 1):
        source = sources.get((result_id, ref.get("source_id")), {}).get("source", {})
        references.append(
            f'<details class="ref" id="ref-{number}"><summary>[{number}] {esc(source.get("title", ref.get("source_id")))} · PDF p.{esc(ref.get("page", "?"))}</summary><blockquote>{esc(ref.get("quote") or "未提供引文")}</blockquote><p class="muted">引文为模型返回的定位信息，未自动标记为人工确认。</p></details>'
        )
    sections.append(
        '<section id="references"><h2>逐项原文引用</h2>'
        + "".join(references)
        + "</section>"
    )
    audit = []
    for r in results:
        audit.append(
            "<table>"
            + "".join(
                f"<tr><th>{esc(key)}</th><td>{esc(value)}</td></tr>"
                for key, value in [
                    ("任务目标", r["task"]["objective"]),
                    ("生成模型", r["provider"].get("model")),
                    ("输入字符上限", r["task"]["budget"]["max_input_characters"]),
                    (
                        "任务费用上限",
                        str(r["task"]["budget"]["max_cost"])
                        + " "
                        + r["task"]["model"].get("currency", ""),
                    ),
                    ("结果指纹", r["artifact_id"]),
                ]
            )
            + "</table>"
        )
    sections.append(
        '<section id="audit"><h2>来源与处理记录</h2>'
        + "".join(audit)
        + '<p class="muted">本报告是溯光已有结果的可视化派生版本，没有新增模型判断，也没有改写原始论文、原生结果或待核对标记。</p></section>'
    )
    navigation = [
        ("overview", "主要结论"),
        ("findings", "完整研究报告"),
        ("review", "待核对事项"),
        ("original", "原页图表"),
        ("references", "原文引用"),
        ("audit", "来源与记录"),
    ]
    print_action = "(async()=>{const images=[...document.querySelectorAll('img')];document.querySelectorAll('details').forEach(e=>e.open=true);images.forEach(e=>e.loading='eager');await Promise.all(images.map(e=>e.decode().catch(()=>{})));window.print()})()"
    document = f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="referrer" content="no-referrer"><title>{esc(title)} · 溯光可视报告</title><style>{CSS}</style></head><body>
<header><div class="eyebrow">溯光 · ALETHEIA NEXUS</div><h1>{esc(title)}</h1><p>研究问题、方法、结果与证据，汇集在一份离线报告中。</p><div class="chips"><span class="chip">{total_pages} 页选定材料</span><span class="chip">{field_count} 个研究字段</span><span class="chip">{claims} 项主张</span><span class="chip">{esc(models)}</span><span class="chip">{datetime.now().strftime("%Y-%m-%d")} 本地导出</span></div></header>
<div class="layout"><nav>{"".join(f'<a href="#{key}">{label}</a>' for key, label in navigation)}</nav><main><div class="toolbar"><button onclick="{esc(print_action)}">打印 / 另存为 PDF</button></div><div class="notice"><strong>阅读提示：保留原有核对状态</strong><p>内容完整呈现已有结果；原文解析、图表解读和科学支持仍可能有缺口。请结合待核对事项与引用阅读。</p></div>{"".join(sections)}</main></div><footer>溯光 · 本地生成 · 原生结果与历史记录保留</footer></body></html>'''
    output.write_text(document, encoding="utf-8")
    return output
