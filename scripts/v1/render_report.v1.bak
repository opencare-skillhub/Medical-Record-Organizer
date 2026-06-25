"""
报告渲染器（T5）

- Markdown：Jinja2 模板填充 → MD 文件
- HTML：Markdown → HTML（markdown 库）+ 内嵌 CSS
- PDF：HTML → PDF（weasyprint，V2）
- DOCX：Markdown → DOCX（python-docx，V2）
- 读取 manifest + timeline.json，按 references/case-report-template.md 结构填充
- 输出到 output/ 目录
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

from jinja2 import Environment, FileSystemLoader, select_autoescape

from scripts.critical_values import check_critical_values, format_alerts_md, format_alerts_html
from scripts.parse_genetics import (
    parse_genetics,
    format_genetic_highlights_md,
    format_genetic_highlights_html,
    build_recent_focus,
    build_consultation_questions,
)

# 模板目录
TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "references"
# 输出目录
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"


def _build_context(
    manifest: Dict[str, Any],
    timeline: Optional[List[Dict[str, Any]]] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """构造模板渲染上下文"""
    demographics = manifest.get("demographics", {}) or {}
    files = manifest.get("files", []) or []

    # 简化 timeline 条目供模板使用
    simplified_timeline: List[Dict[str, Any]] = []
    if timeline:
        for item in timeline:
            simplified_timeline.append({
                "dates": item.get("dates", []),
                "title": item.get("title") or item.get("file", ""),
                "category": item.get("category", ""),
            })

    # 检验指标趋势表（1 期简化：按日期 + 类别聚合关键数值）
    lab_trend: List[Dict[str, str]] = []
    imaging_summary: List[Dict[str, str]] = []
    pathology: List[Dict[str, str]] = []
    medication: Dict[str, List[str]] = {"current": [], "history": []}
    gaps: List[str] = []

    # 按分类汇总
    categories = manifest.get("categories_summary", {}) or {}
    if not categories:
        gaps.append("缺少检验指标数据")
    if "imaging" not in categories:
        gaps.append("缺少影像检查数据")
    if "pathology" not in categories:
        gaps.append("缺少病理报告数据")
    if "medication" not in categories:
        gaps.append("缺少用药方案数据")

    # 为每个文件构造目录条目
    file_entries = []
    for fe in files:
        file_entries.append({
            "title": fe.get("title") or fe.get("original_name", ""),
            "date": fe.get("date_detected") or "日期待确认",
            "category": fe.get("category") or "未分类",
        })

    ctx = {
        "demographics": demographics,
        "created_at": manifest.get("created_at"),
        "updated_at": manifest.get("updated_at"),
        "timeline": simplified_timeline,
        "lab_trend": lab_trend,
        "imaging_summary": imaging_summary,
        "pathology": pathology,
        "medication": medication,
        "files": file_entries,
        "gaps": gaps,
    }
    if extra:
        ctx.update(extra)
    return ctx


def compute_report_context(
    manifest: Dict[str, Any],
    *,
    timeline: Optional[List[Dict[str, Any]]] = None,
    extracted_texts: Optional[List[str]] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """构造完整报告上下文（含危急值 + 基因检测 + 所有 HTML 模板变量）"""
    ctx = _build_context(manifest, timeline=timeline, extra=extra)

    # 合并所有提取文本
    combined_text = "\n".join(extracted_texts or [])

    # 危急值
    alerts = check_critical_values(combined_text)
    ctx["critical_alerts"] = [
        {
            "item_name": a.item_name,
            "value": a.value,
            "unit": a.unit,
            "level": a.level,
            "level_label": a.level_label,
            "message": a.message,
            "color": a.color,
            "emoji": a.emoji,
            "action": a.action,
            "category": a.category,
        }
        for a in alerts
    ]
    ctx["critical_alerts_md"] = format_alerts_md(alerts)
    ctx["critical_alerts_html"] = format_alerts_html(alerts)
    ctx["has_critical"] = any(a["level"] >= 4 for a in ctx["critical_alerts"])

    # 基因检测
    highlights = parse_genetics(combined_text)
    ctx["genetic_highlights"] = [
        {
            "gene": h.gene,
            "mutation": h.mutation,
            "position": h.position,
            "vaf": h.vaf,
            "drug_sensitivity": h.drug_sensitivity,
            "pathogenic": h.pathogenic,
            "immune_marker": h.immune_marker,
            "level": h.level,
            "abundance": h.abundance,
            "breakthrough_type": h.breakthrough_type,
            "pathology_type": h.pathology_type,
            "notes": h.notes,
        }
        for h in highlights
    ]
    ctx["genetic_highlights_md"] = format_genetic_highlights_md(highlights)
    ctx["genetic_highlights_html"] = format_genetic_highlights_html(highlights)

    # 近期关注重点 + 咨询问题
    mdt_analysis = profile.get('mdt_analysis') or {}
    mdt_concerns = mdt_analysis.get('concerns') or []
    if mdt_concerns:
        focus_items: List[str] = []
        for item in mdt_concerns:
            if isinstance(item, dict):
                title = item.get('title') or item.get('analysis') or ''
                analysis = item.get('analysis') or ''
                priority = item.get('priority') or 'medium'
                disciplines = item.get('disciplines') or ([item.get('discipline')] if item.get('discipline') else [])
                prefix = '⚠️' if priority == 'high' else ('⚪' if priority == 'low' else '•')
                if disciplines:
                    title = f"{title}（{'/'.join([d for d in disciplines if d])}）"
                focus_items.append(f"{prefix} {title}：{analysis}" if analysis else f"{prefix} {title}")
            else:
                focus_items.append(str(item))
        ctx["recent_focus"] = focus_items
    else:
        ctx["recent_focus"] = build_recent_focus(alerts, highlights, timeline or [])
    ctx["consultation_questions"] = build_consultation_questions(
        ctx.get("gaps", []), alerts, highlights
    )

    # HTML 模板所需补充变量
    demographics = manifest.get("demographics", {}) or {}
    ctx["report_title"] = demographics.get("primary_diagnosis", "患者病情概览") or "患者病情概览"

    # pathology_tag：从病理数据中提取标签
    pathology_items = ctx.get("pathology", [])
    if pathology_items:
        tags = []
        for p in pathology_items:
            if p.get("type"):
                tags.append(p["type"])
            elif p.get("summary"):
                tags.append(p["summary"][:20])
        ctx["pathology_tag"] = " | ".join(tags) if tags else ""
    else:
        ctx["pathology_tag"] = ""

    # ihc_note：免疫组化分析备注
    ihc_items = [h for h in ctx.get("genetic_highlights", []) if h.get("category") == "ihc"]
    if ihc_items:
        ctx["ihc_note"] = "免疫组化结果已标注，请结合临床判断。"
    else:
        ctx["ihc_note"] = ""

    # medication_summary / medication_table / medication_prescription_date
    medication = ctx.get("medication", {})
    med_current = medication.get("current", [])
    med_history = medication.get("history", [])
    ctx["medication_summary"] = [
        {"label": "当前用药", "value": f"{len(med_current)} 种", "is_critical": False},
        {"label": "历史用药", "value": f"{len(med_history)} 种", "is_critical": False},
    ]
    ctx["medication_table"] = []  # 1 期简化，后续可从 manifest 中提取详细表格
    ctx["medication_prescription_date"] = manifest.get("updated_at", "")[:10] if manifest.get("updated_at") else ""

    # chart_svg_ca199 / chart_svg：1 期简化，留空由前端或后续扩展
    ctx["chart_svg_ca199"] = ""
    ctx["chart_svg"] = ""
    ctx["chart_svg_normalized"] = ""
    ctx["chart_svg_absolute"] = ""
    ctx["marker_sync_alert"] = ""

    # key_concerns：从 recent_focus 构建
    ctx["key_concerns"] = [{"text": t, "is_alert": True} for t in ctx.get("recent_focus", [])]

    # files：净化文件名/标题，防止 XSS
    ctx["files"] = [
        {
            "title": _strip_html(fe.get("title") or fe.get("original_name", "")),
            "date": fe.get("date_detected") or "日期待确认",
        }
        for fe in manifest.get("files", [])
    ]

    # 净化 demographics 中的动态字段
    if "name" in ctx.get("demographics", {}):
        ctx["demographics"] = dict(ctx["demographics"])
        ctx["demographics"]["name"] = _strip_html(ctx["demographics"].get("name", ""))

    # 净化 consultation_questions
    ctx["consultation_questions"] = [_strip_html(q) for q in ctx.get("consultation_questions", [])]

    # 净化 timeline 中的 title
    if timeline:
        ctx["timeline"] = []
        for item in timeline:
            new_item = dict(item)
            if "title" in new_item:
                new_item["title"] = _strip_html(new_item["title"])
            ctx["timeline"].append(new_item)

    return ctx


def _strip_html(text: str) -> str:
    """剥离 HTML 标签和事件处理器，防止 XSS"""
    import re
    # 移除 HTML 标签
    text = re.sub(r'<[^>]+>', '', str(text))
    # 移除事件处理器属性（onerror=, onload=, onclick= 等）
    text = re.sub(r'\s*on\w+\s*=\s*("[^"]*"|\'[^\']*\')', '', text)
    return text.strip()


def render_md(
    manifest: Dict[str, Any],
    *,
    timeline: Optional[List[Dict[str, Any]]] = None,
    output_path: Optional[Path] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Path:
    """渲染 Markdown 报告"""
    if output_path is None:
        output_path = DEFAULT_OUTPUT_DIR / "case-report.md"

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(enabled_extensions=("md",)),
        keep_trailing_newline=True,
    )
    template = env.get_template("case-report-template.md")
    ctx = _build_context(manifest, timeline=timeline, extra=extra)
    content = template.render(**ctx)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")
    logger.info("Markdown 报告已生成: %s", output_path)
    return output_path


def render_html(
    manifest: Dict[str, Any],
    *,
    timeline: Optional[List[Dict[str, Any]]] = None,
    output_path: Optional[Path] = None,
    extra: Optional[Dict[str, Any]] = None,
    report_context: Optional[Dict[str, Any]] = None,
) -> Path:
    """渲染 HTML 报告（直接使用 html-report-template.html）"""
    if output_path is None:
        output_path = DEFAULT_OUTPUT_DIR / "case-report.html"

    # 若提供了 report_context，优先使用；否则自动计算
    if report_context is None:
        report_context = compute_report_context(
            manifest,
            timeline=timeline,
            extra=extra,
        )

    # 直接渲染 HTML 模板
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(enabled_extensions=("html",)),
        keep_trailing_newline=True,
    )
    template = env.get_template("html-report-template.html")

    # 最终兜底：渲染前再 sanitize 一遍动态字段，防止绕过
    safe_context = _sanitize_report_context(report_context)

    full_html = template.render(**safe_context)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(full_html, encoding="utf-8")
    logger.info("HTML 报告已生成: %s", output_path)
    return output_path


def _sanitize_report_context(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """递归 sanitize report_context 中的动态字符串，防止 XSS"""
    import re
    from copy import deepcopy

    ctx = deepcopy(ctx)
    # 移除事件处理器属性
    _ON_EVENT_RE = re.compile(r'\s*on\w+\s*=\s*("[^"]*"|\'[^\']*\')')

    def _clean_value(v):
        if isinstance(v, str):
            # 移除事件处理器
            v = _ON_EVENT_RE.sub('', v)
            return v
        if isinstance(v, dict):
            return {k: _clean_value(val) for k, val in v.items()}
        if isinstance(v, list):
            return [_clean_value(item) for item in v]
        return v

    # 重点字段 sanitize
    for key in [
        "report_title",
        "consultation_questions",
        "recent_focus",
        "key_concerns",
        "files",
        "timeline",
        "genetic_highlights",
        "critical_alerts",
    ]:
        if key in ctx:
            ctx[key] = _clean_value(ctx[key])

    # demographics
    if "demographics" in ctx and isinstance(ctx["demographics"], dict):
        ctx["demographics"] = _clean_value(ctx["demographics"])

    return ctx


def render_pdf(
    manifest: Dict[str, Any],
    *,
    timeline: Optional[List[Dict[str, Any]]] = None,
    output_path: Optional[Path] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Path:
    """渲染 PDF 报告（V2：需要安装 weasyprint）"""
    if output_path is None:
        output_path = DEFAULT_OUTPUT_DIR / "case-report.pdf"

    html_path = DEFAULT_OUTPUT_DIR / "_tmp_report.html"
    render_html(manifest, timeline=timeline, output_path=html_path, extra=extra)
    html_text = html_path.read_text(encoding="utf-8")

    try:
        from weasyprint import HTML
    except ImportError as exc:
        raise RuntimeError("weasyprint 未安装，请运行: pip install weasyprint") from exc

    output_path.parent.mkdir(parents=True, exist_ok=True)
    HTML(string=html_text).write_pdf(str(output_path))
    logger.info("PDF 报告已生成: %s", output_path)
    return output_path


def render_docx(
    manifest: Dict[str, Any],
    *,
    timeline: Optional[List[Dict[str, Any]]] = None,
    output_path: Optional[Path] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Path:
    """渲染 DOCX 报告（V2：需要安装 python-docx，将 Markdown 内容写入 Word）"""
    if output_path is None:
        output_path = DEFAULT_OUTPUT_DIR / "case-report.docx"

    md_path = DEFAULT_OUTPUT_DIR / "_tmp_report.docx.md"
    render_md(manifest, timeline=timeline, output_path=md_path, extra=extra)
    md_text = md_path.read_text(encoding="utf-8")

    try:
        import docx  # python-docx
    except ImportError as exc:
        raise RuntimeError("python-docx 未安装，请运行: pip install python-docx") from exc

    doc = docx.Document()
    doc.add_heading("病例档案", level=1)

    for line in md_text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("# "):
            doc.add_heading(line[2:], level=1)
        elif line.startswith("## "):
            doc.add_heading(line[3:], level=2)
        elif line.startswith("- "):
            doc.add_paragraph(line[2:], style="List Bullet")
        else:
            doc.add_paragraph(line)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(output_path))
    logger.info("DOCX 报告已生成: %s", output_path)
    return output_path
