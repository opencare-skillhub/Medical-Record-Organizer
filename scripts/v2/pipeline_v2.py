"""
v2 端到端流水线

流程：
  原始 .md -> 脱敏 -> Map LLM -> Shuffle -> Reduce LLM -> Profile -> 报告
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# 确保项目根在 sys.path 中（支持直接 python scripts/v2/pipeline_v2.py 运行）
_ProjectRoot = Path(__file__).resolve().parent.parent.parent
if str(_ProjectRoot) not in sys.path:
    sys.path.insert(0, str(_ProjectRoot))

# 自动加载 .env（如果存在）
_dotenv_path = _ProjectRoot / ".env"
if _dotenv_path.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(str(_dotenv_path), override=True)
    except ImportError:
        pass  # python-dotenv 未安装时静默跳过

logger = logging.getLogger(__name__)

from scripts.v2.desensitize import desensitize_directory
from scripts.v2.map_extract import extract_batch
from scripts.v2.reduce_merge import reduce_lab_trends, reduce_imaging_narrative, reduce_medication_history
from scripts.v2.shuffle_group import group_by_type, merge_lab_trends

try:
    from jinja2 import Environment, FileSystemLoader, Template
    _JINJA2_AVAILABLE = True
except ImportError:
    _JINJA2_AVAILABLE = False


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_pipeline(
    input_dir: str,
    output_dir: str,
    *,
    patient_id: str = 'P_report_mess',
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """执行 v2 MapReduce 流水线。"""
    input_path = Path(input_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    md_files = sorted(input_path.glob('*.md'))
    if not md_files:
        return {'patient_id': patient_id, 'status': 'no_input', 'files': 0}

    # Phase 1: 脱敏
    sanitized_dir = output_path / 'sanitized'
    mappings = desensitize_directory(str(input_path), str(sanitized_dir))

    # Phase 2: Map
    map_dir = output_path / 'map'
    extracted = extract_batch(str(sanitized_dir), str(map_dir), model=model)

    # Phase 3: Shuffle
    groups = group_by_type(extracted)
    lab_trends = merge_lab_trends(groups.get('lab', []))

    # Phase 4: Reduce
    lab_analysis = reduce_lab_trends(lab_trends, model=model)
    med_timeline = reduce_medication_history(groups.get('medication', []), model=model)
    imaging_narrative = reduce_imaging_narrative(groups.get('imaging', []), model=model)

    # Phase 5: Profile 组装
    profile: Dict[str, Any] = {
        'patient_id': patient_id,
        'generated_at': _now_iso(),
        'input_dir': str(input_path),
        'file_count': len(md_files),
        'map_count': len(extracted),
        'groups': {k: len(v) for k, v in groups.items()},
        'lab_trends': lab_trends,
        'lab_analysis': lab_analysis,
        'medication_timeline': med_timeline,
        'imaging_narrative': imaging_narrative,
        'mappings_path': str(output_path / 'mappings.json'),
        'output_dir': str(output_path),
    }

    (output_path / 'profile.json').write_text(
        json.dumps(profile, ensure_ascii=False, indent=2), encoding='utf-8'
    )
    (output_path / 'mappings.json').write_text(
        json.dumps(mappings, ensure_ascii=False, indent=2), encoding='utf-8'
    )

    # Phase 6: 渲染报告
    _render_reports(profile, groups, output_path)

    logger.info(
        'v2 流水线完成: patient=%s files=%d groups=%s',
        patient_id,
        len(extracted),
        ','.join(f'{k}={len(v)}' for k, v in groups.items()),
    )
    return profile


def _render_reports(
    profile: Dict[str, Any],
    groups: Dict[str, List[Dict[str, Any]]],
    output_path: Path,
) -> None:
    """生成 HTML + Markdown 报告。优先使用 html-report-template.html 模板。"""
    # 构造模板上下文
    ctx = _build_template_context(profile, groups)

    html_path = output_path / 'case_report.html'
    md_path = output_path / 'case_report.md'

    # 尝试使用 Jinja2 模板渲染 HTML
    if _JINJA2_AVAILABLE:
        template_path = _ProjectRoot / 'references' / 'html-report-template.html'
        if template_path.exists():
            try:
                env = Environment(
                    loader=FileSystemLoader(str(template_path.parent)),
                    autoescape=True,
                    trim_blocks=True,
                    lstrip_blocks=True,
                )
                template = env.get_template(template_path.name)
                html = template.render(**ctx)
                html_path.write_text(html, encoding='utf-8')
                logger.info('HTML 报告已生成: %s', html_path)
            except Exception as exc:
                logger.warning('模板渲染失败，回退到基础 HTML: %s', exc)
                _render_basic_html(ctx, html_path)
        else:
            logger.warning('模板文件不存在: %s，使用基础 HTML', template_path)
            _render_basic_html(ctx, html_path)
    else:
        logger.warning('Jinja2 未安装，使用基础 HTML')
        _render_basic_html(ctx, html_path)

    # 同时生成 Markdown 报告
    _render_markdown(profile, groups, md_path)


# ---------------------------------------------------------------------------
# 模板上下文构建
# ---------------------------------------------------------------------------

def _build_template_context(profile: Dict[str, Any], groups: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    """把 v2 profile / groups 映射到 html-report-template.html 所需的上下文。"""
    # 从 profile 中读取 map 目录路径
    output_dir = Path(profile.get('output_dir') or profile.get('input_dir') or '.')
    map_dir = output_dir / 'map'
    
    # 读取所有 map JSON
    all_items = []
    if map_dir.exists():
        for jf in map_dir.glob('*.json'):
            try:
                item = json.loads(jf.read_text(encoding='utf-8'))
                all_items.append(item)
            except Exception:
                pass
    
    # 如果 map_dir 没有数据，使用 groups 参数（向后兼容）
    if not all_items and isinstance(groups, dict):
        # groups 可能是计数（int）或列表（list）
        temp_items = []
        for k, v in groups.items():
            if isinstance(v, list):
                for item in v:
                    item_copy = dict(item)
                    item_copy.setdefault('report_type', k)
                    temp_items.append(item_copy)
        if temp_items:
            all_items = temp_items

    # demographics
    demographics = {"name": "", "age": "", "gender": "", "primary_diagnosis": ""}
    for item in all_items:
        pi = item.get("patient_info")
        if isinstance(pi, dict) and not demographics["name"]:
            demographics = {
                "name": pi.get("name", ""),
                "age": pi.get("age", ""),
                "gender": pi.get("gender", ""),
                "primary_diagnosis": pi.get("primary_diagnosis", ""),
            }
            break

    # timeline（从所有报告日期构建）
    timeline = []
    for item in all_items:
        rd = item.get("report_date") or ""
        if rd:
            timeline.append({
                "dates": [rd],
                "title": item.get("_source_file", ""),
                "category": item.get("report_type", ""),
                "note": item.get("conclusion") or item.get("findings") or "",
            })
    timeline.sort(key=lambda x: x.get("dates", [""])[0])

    # pathology & genetic_highlights
    pathology = []
    genetic_highlights = []
    for item in all_items:
        if item.get("report_type") == "pathology":
            pathology.append({
                "date": item.get("report_date", ""),
                "type": item.get("specimen_type", ""),
                "summary": item.get("diagnosis", "") or item.get("conclusion", ""),
            })
            for gene in item.get("test_items", []) or []:
                gh = {
                    "gene": gene.get("gene_name", ""),
                    "mutation": gene.get("detection_result", ""),
                    "result": gene.get("detection_result", ""),
                    "category": gene.get("category", ""),
                    "pathogenic": gene.get("is_pathogenic", False),
                    "tags": [],
                }
                if gene.get("clinical_significance"):
                    gh["tags"].append(gene["clinical_significance"])
                genetic_highlights.append(gh)

    # medication
    medication_summary = []
    medication_table = []
    med_tl = profile.get("medication_timeline") or {}
    for regimen in med_tl.get("regimens", []) or []:
        medication_summary.append({
            "label": regimen.get("name", ""),
            "value": regimen.get("cycles", ""),
            "is_critical": False,
        })
    for cycle in med_tl.get("cycles", []) or []:
        for drug in cycle.get("drugs", []) or []:
            medication_table.append({
                "name": drug.get("name", ""),
                "dose": drug.get("dose", ""),
                "route": drug.get("route", ""),
                "purpose": drug.get("purpose", ""),
            })

    # imaging_summary
    imaging_summary = []
    for item in all_items:
        if item.get("report_type") == "imaging":
            findings = item.get("findings") or item.get("diagnostic_impression") or []
            if isinstance(findings, list):
                findings_text = "; ".join(str(f) for f in findings if f)
            else:
                findings_text = str(findings)
            imaging_summary.append({
                "date": item.get("report_date", "日期待确认"),
                "modality": item.get("modality", "CT"),
                "findings": findings_text or item.get("conclusion", ""),
            })

    # lab_trend & tumor_marker_tables
    lab_trends = profile.get("lab_trends") or {}
    lab_trend = []
    tumor_marker_tables = {}
    all_dates = set()
    indicator_names = []
    
    # 肿瘤标志物中文名 -> 标准缩写映射
    _MARKER_ALIASES = {
        "癌胚抗原": "CEA",
        "糖类抗原19-9": "CA19-9",
        "糖类抗原19-9(高值)": "CA19-9",
        "糖类抗原125": "CA125",
        "糖类抗原15-3": "CA15-3",
        "糖类抗原724": "CA724",
        "糖类抗原72-4": "CA724",
        "甲胎蛋白": "AFP",
        "前列腺特异性抗原": "PSA",
        "糖类抗原153": "CA153",
        "糖类抗原242": "CA242",
        "糖类抗原50": "CA50",
    }
    
    for indicator, data in lab_trends.items():
        indicator_names.append(indicator)
        for row in data.get("trend", []):
            all_dates.add(row.get("date", ""))
    all_dates = sorted(all_dates)
    for date in all_dates:
        row = {"date": date}
        for indicator in indicator_names:
            data = lab_trends[indicator]
            for trend_row in data.get("trend", []):
                if trend_row.get("date") == date:
                    row[indicator] = trend_row.get("value", "")
                    break
        lab_trend.append(row)
        # tumor_marker_tables：把中文指标名映射为标准缩写
        for indicator in indicator_names:
            standard_name = _MARKER_ALIASES.get(indicator, indicator)
            # 匹配标准缩写或原始名称中包含 CA/CEA/AFP/PSA 的
            is_tumor_marker = (
                standard_name in ["CEA", "CA199", "CA125", "CA724", "AFP", "PSA", "CA153", "CA242", "CA50"]
                or any(k in indicator for k in ["CEA", "CA", "AFP", "PSA"])
            )
            if is_tumor_marker:
                data = lab_trends[indicator]
                unit = data.get("unit", "")
                ref_range = data.get("ref_range", "")
                rows = []
                for tr in data.get("trend", []):
                    val = tr.get("value", "")
                    try:
                        num_val = float(val) if val != "" else None
                        prev = rows[-1]["value"] if rows else None
                        change = ""
                        if num_val is not None and prev is not None:
                            diff = num_val - prev
                            change = f"+{diff:.2f}" if diff > 0 else f"{diff:.2f}"
                    except (ValueError, TypeError):
                        change = ""
                    rows.append({
                        "date": tr.get("date", ""),
                        "value": val,
                        "change": change,
                        "note": "异常" if tr.get("abnormal") else "",
                        "is_abnormal": tr.get("abnormal", False),
                    })
                tumor_marker_tables[standard_name] = {
                    "unit": unit,
                    "ref_range": ref_range,
                    "rows": rows,
                }

    # critical_alerts
    critical_alerts = []
    for indicator, data in lab_trends.items():
        for row in data.get("trend", []):
            if row.get("abnormal"):
                critical_alerts.append({
                    "item_name": indicator,
                    "value": row.get("value", ""),
                    "unit": row.get("unit", ""),
                    "level": 2,
                    "level_label": "Ⅱ级（轻度异常）",
                    "message": f"{indicator}: {row.get('value', '')} {row.get('unit', '')}（异常）",
                    "color": "#f39c12",
                    "emoji": "🟡",
                    "action": "下次就诊告知医生",
                })
    has_critical = bool(critical_alerts)

    # key_concerns
    key_concerns = []
    img_narr = profile.get("imaging_narrative") or {}
    if img_narr.get("data_limitation"):
        key_concerns.append({"text": img_narr["data_limitation"], "is_alert": False})
    lab_a = profile.get("lab_analysis") or {}
    for indicator, data in lab_a.items():
        if data.get("alert_level") in ("warning", "critical"):
            key_concerns.append({
                "text": f"{indicator}: {data.get('clinical_inference', '')}",
                "is_alert": data.get("alert_level") == "critical",
            })

    # consultation_questions
    consultation_questions = [
        "缺少完整检验指标趋势数据，建议补充历次肿瘤标志物结果",
        "缺少用药方案记录，建议补充化疗/靶向治疗详细信息",
        "缺少病理报告，建议补充组织学类型和免疫组化结果",
    ]

    # files
    files = []
    for item in all_items:
        files.append({
            "title": item.get("_source_file", ""),
            "date": item.get("report_date", "日期待确认"),
            "category": item.get("report_type", "未分类"),
        })

    # gaps
    gaps = [
        "缺少完整检验指标趋势数据" if not lab_trends else "",
        "缺少用药方案记录" if not med_tl else "",
        "缺少病理报告" if not pathology else "",
        "缺少患者基本信息" if not demographics.get("name") else "",
    ]
    gaps = [g for g in gaps if g]

    ctx = {
        "demographics": demographics,
        "timeline": timeline,
        "pathology": pathology,
        "genetic_highlights": genetic_highlights,
        "medication_summary": medication_summary,
        "medication_table": medication_table,
        "imaging_summary": imaging_summary,
        "tumor_marker_tables": tumor_marker_tables,
        "lab_trend": lab_trend,
        "key_concerns": key_concerns,
        "consultation_questions": consultation_questions,
        "files": files,
        "gaps": gaps,
        "critical_alerts": critical_alerts,
        "has_critical": has_critical,
        "updated_at": profile.get("generated_at", ""),
        "medication": {"current": [], "history": med_tl.get("regimens", []) or []},
    }
    return ctx


# ---------------------------------------------------------------------------
# 兜底 HTML（无模板时使用）
# ---------------------------------------------------------------------------

def _render_basic_html(ctx: Dict[str, Any], output_path: Path) -> None:
    """生成基础 HTML（无 Jinja2 模板时的兜底）。"""
    lines = [
        "<!DOCTYPE html><html lang='zh-CN'><head>",
        "<meta charset='UTF-8'><meta name='viewport' content='width=device-width, initial-scale=1.0'>",
        "<title>患病情档案</title>",
        "<style>",
        "body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','Microsoft YaHei',sans-serif;max-width:900px;margin:0 auto;padding:16px;background:#f5f5f5;color:#333}",
        ".card{background:#fff;border-radius:8px;box-shadow:0 2px 8px rgba(0,0,0,.08);margin-bottom:16px;padding:16px}",
        ".card-header{font-size:16px;font-weight:700;margin-bottom:12px;padding-bottom:8px;border-bottom:1px solid #e5e7eb}",
        "table{width:100%;border-collapse:collapse;font-size:14px}",
        "th,td{border:1px solid #e5e7eb;padding:8px 12px;text-align:left}",
        "th{background:#f9fafb;font-weight:600}",
        ".disclaimer{margin-top:24px;padding:16px;background:#fff3cd;border:1px solid #ffc107;border-radius:8px;font-size:13px;color:#856404}",
        "</style></head><body>",
        "<h1>患病情档案</h1>",
    ]

    demographics = ctx.get("demographics") or {}
    lines.append("<div class='card'><div class='card-header'>患者基础信息</div>")
    lines.append(f"<p><b>姓名：</b>{demographics.get('name','')}</p>")
    lines.append(f"<p><b>性别：</b>{demographics.get('gender','')}</p>")
    lines.append(f"<p><b>年龄：</b>{demographics.get('age','')}岁</p>")
    lines.append("</div>")

    # 时间线
    timeline = ctx.get("timeline") or []
    if timeline:
        lines.append("<div class='card'><div class='card-header'>就诊经历时间轴</div><ul>")
        for item in timeline:
            d = (item.get("dates") or ["日期待确认"])[0]
            lines.append(f"<li><b>{d}</b> — {item.get('title','')} ({item.get('category','')})</li>")
        lines.append("</ul></div>")

    # 检验指标
    lab_trend = ctx.get("lab_trend") or []
    if lab_trend:
        lines.append("<div class='card'><div class='card-header'>检查指标趋势</div><table><thead><tr>")
        headers = list(lab_trend[0].keys())
        for h in headers:
            lines.append(f"<th>{h}</th>")
        lines.append("</tr></thead><tbody>")
        for row in lab_trend:
            lines.append("<tr>")
            for h in headers:
                lines.append(f"<td>{row.get(h,'')}</td>")
            lines.append("</tr>")
        lines.append("</tbody></table></div>")

    # 影像
    imaging = ctx.get("imaging_summary") or []
    if imaging:
        lines.append("<div class='card'><div class='card-header'>影像检查</div><table><thead><tr><th>日期</th><th>项目</th><th>发现</th></tr></thead><tbody>")
        for item in imaging:
            lines.append(f"<tr><td>{item.get('date','')}</td><td>{item.get('modality','')}</td><td>{item.get('findings','')}</td></tr>")
        lines.append("</tbody></table></div>")

    # 用药
    med = ctx.get("medication") or {}
    lines.append("<div class='card'><div class='card-header'>用药方案</div>")
    if med.get("history"):
        lines.append("<ul>")
        for m in med["history"]:
            lines.append(f"<li>{m}</li>")
        lines.append("</ul>")
    else:
        lines.append("<p>暂无用药数据</p>")
    lines.append("</div>")

    # 免责声明
    lines.append("<div class='disclaimer'>")
    lines.append("⚠️ 免责声明：本病例档案仅为医疗资料整理与结构化归档，不构成任何诊断或治疗建议。")
    lines.append("</div>")

    lines.append("</body></html>")
    output_path.write_text("\n".join(lines), encoding='utf-8')


# ---------------------------------------------------------------------------
# Markdown 报告
# ---------------------------------------------------------------------------

def _render_markdown(profile: Dict[str, Any], groups: Dict[str, List[Dict[str, Any]]], output_path: Path) -> None:
    """生成 Markdown 报告。"""
    lines: List[str] = []
    lines.append('# v2 病案整理报告')
    lines.append('')
    lines.append(f'- 患者ID：{profile.get("patient_id", "")}')
    lines.append(f'- 生成时间：{profile.get("generated_at", "")}')
    lines.append(f'- 处理文件数：{profile.get("file_count", 0)}')
    lines.append('')

    # 分类摘要
    lines.append('## 分类摘要')
    lines.append('')
    for group, count in sorted((profile.get('groups') or {}).items()):
        lines.append(f'- {group}: {count}')
    lines.append('')

    # 检验指标
    lab_trends = profile.get('lab_trends') or {}
    if lab_trends:
        lines.append('## 检验指标趋势')
        lines.append('')
        for indicator, data in sorted(lab_trends.items()):
            lines.append(f'### {indicator}')
            trend = data.get('trend') or []
            if trend:
                lines.append('| 日期 | 数值 | 单位 |')
                lines.append('|------|------|------|')
                for item in trend:
                    lines.append(f'| {item.get("date", "")} | {item.get("value", "")} | {item.get("unit", "")} |')
            lab_a = (profile.get('lab_analysis') or {}).get(indicator) or {}
            if lab_a.get('trend_summary'):
                lines.append(f'- 趋势：{lab_a["trend_summary"]}')
                lines.append(f'- 预警：{lab_a.get("alert_level", "")}')
                lines.append(f'- 临床推断：{lab_a.get("clinical_inference", "")}')
            lines.append('')

    # 用药
    med = profile.get('medication_timeline') or {}
    if med:
        lines.append('## 用药时间线')
        lines.append('')
        lines.append('```json')
        lines.append(json.dumps(med, ensure_ascii=False, indent=2))
        lines.append('```')
        lines.append('')

    # 影像
    img = profile.get('imaging_narrative') or {}
    if img:
        lines.append('## 影像演变叙事')
        lines.append('')
        lines.append('```json')
        lines.append(json.dumps(img, ensure_ascii=False, indent=2))
        lines.append('```')
        lines.append('')

    # 原始 Map 摘要
    lines.append('## Map 提取摘要')
    lines.append('')
    for item in groups.get('lab', [])[:10]:
        lines.append(f'- {item.get("_source_file", "")}: {item.get("report_type", "")} ({item.get("confidence", "")})')
    lines.append('')

    output_path.write_text('\n'.join(lines), encoding='utf-8')


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    """命令行入口。"""
    import argparse
    
    parser = argparse.ArgumentParser(description='v2 病案整理流水线')
    parser.add_argument('--input-dir', required=True, help='输入目录（.md 文件）')
    parser.add_argument('--output-dir', required=True, help='输出目录')
    parser.add_argument('--patient-id', default='P_report_mess', help='患者ID')
    parser.add_argument('--model', help='LLM 模型名称')
    parser.add_argument('--format', choices=['html', 'md', 'all'], default='all', help='输出格式')
    parser.add_argument('--open', action='store_true', help='生成后自动打开 HTML')
    parser.add_argument('--log-level', default='INFO', help='日志级别')
    args = parser.parse_args(argv)
    
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO))
    
    input_path = Path(args.input_dir)
    if not input_path.exists() or not input_path.is_dir():
        print(f"❌ 输入目录不存在: {input_path}")
        return 1
    
    print(f"📋 开始运行 v2 流水线...")
    print(f"   输入目录: {input_path}")
    print(f"   输出目录: {args.output_dir}")
    print(f"   患者ID: {args.patient_id}")
    print(f"   输出格式: {args.format}")
    print("=" * 60)
    
    try:
        profile = run_pipeline(
            input_dir=str(input_path),
            output_dir=args.output_dir,
            patient_id=args.patient_id,
            model=args.model,
        )
        
        print("\n" + "=" * 60)
        print("✅ v2 流水线运行完毕！")
        print(f"   患者ID: {profile.get('patient_id')}")
        print(f"   处理文件数: {profile.get('file_count', 0)}")
        print(f"   分类: {profile.get('groups', {})}")
        
        # 打开 HTML
        if args.format in ('html', 'all'):
            output_path = Path(args.output_dir)
            html_file = output_path / 'case_report.html'
            if html_file.exists() and args.open:
                import webbrowser
                webbrowser.open(f"file://{html_file}")
                print(f"🌐 已打开报告: {html_file}")
        
        return 0
        
    except Exception as exc:
        print(f"\n❌ 流水线运行失败: {exc}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
