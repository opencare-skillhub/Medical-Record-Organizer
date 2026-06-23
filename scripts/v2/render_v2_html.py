#!/usr/bin/env python3
"""
v2 HTML 报告渲染器

读取 v2 pipeline 输出的 profile.json，调用 render_html_v2 生成最终 HTML。
"""
import json
import sys
from pathlib import Path

# 添加项目根到 sys.path
project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))

from scripts.render_html_v2 import render_html_v2


def build_manifest_from_profile(profile: dict) -> tuple:
    """从 v2 profile 和 map JSON 构造 render_html_v2 需要的 manifest 结构。"""
    patient_id = profile.get("patient_id", "unknown")
    v2_output_dir = Path("/Users/qinxiaoqiang/Downloads/patient-record-organizer/temp_v2_output")
    map_dir = v2_output_dir / "map"

    # 读取所有 map JSON
    all_items = []
    if map_dir.exists():
        for jf in map_dir.glob("*.json"):
            try:
                item = json.loads(jf.read_text(encoding="utf-8"))
                all_items.append(item)
            except Exception:
                pass

    # 按 type 分组
    groups = {}
    for item in all_items:
        rt = item.get("report_type", "other") or "other"
        groups.setdefault(rt, []).append(item)

    # 1. demographics
    demographics = {"name": "", "age": "", "gender": "", "primary_diagnosis": ""}
    # 从 lab 报告中提取患者信息
    for item in all_items:
        if item.get("report_type") == "lab" and item.get("patient_info"):
            pi = item["patient_info"]
            if isinstance(pi, dict):
                demographics["name"] = pi.get("name", "")
                demographics["age"] = pi.get("age", "")
                demographics["gender"] = pi.get("gender", "")
                break

    # 2. files 列表
    files = []
    for item in all_items:
        files.append({
            "title": item.get("_source_file", ""),
            "date": item.get("report_date", "日期待确认"),
            "category": item.get("report_type", "未分类"),
        })

    # 3. 从 lab_trends 构造 lab_trend 表（用于趋势图）
    lab_trends = profile.get("lab_trends", {}) or {}
    lab_trend = []
    # 收集所有日期和指标
    all_dates = set()
    indicator_names = []
    for indicator, data in lab_trends.items():
        indicator_names.append(indicator)
        for row in data.get("trend", []):
            all_dates.add(row.get("date", ""))
    all_dates = sorted(all_dates)

    # 构造 lab_trend 表（每行一个日期，每列一个指标）
    for date in all_dates:
        row = {"date": date}
        for indicator in indicator_names:
            data = lab_trends[indicator]
            # 查找该日期的值
            for trend_row in data.get("trend", []):
                if trend_row.get("date") == date:
                    row[indicator] = trend_row.get("value", "")
                    break
        lab_trend.append(row)

    # 4. imaging_summary
    imaging_narrative = profile.get("imaging_narrative", {}) or {}
    imaging_summary = []
    for item in all_items:
        if item.get("report_type") == "imaging":
            findings = item.get("findings", []) or item.get("diagnostic_impression", []) or []
            if findings:
                imaging_summary.append({
                    "date": item.get("report_date", "日期待确认"),
                    "modality": item.get("modality", "CT"),
                    "findings": "; ".join(str(f) for f in findings if f),
                })

    # 5. medication
    medication_timeline = profile.get("medication_timeline", {}) or {}
    medication = {
        "current": [],
        "history": medication_timeline.get("regimens", []) or [],
    }

    # 6. genetic_highlights
    genetic_highlights = []
    for item in all_items:
        if item.get("report_type") == "pathology":
            for gene in item.get("test_items", []) or []:
                genetic_highlights.append({
                    "gene": gene.get("gene_name", ""),
                    "mutation": gene.get("detection_result", ""),
                    "position": "",
                })

    # 7. critical_alerts
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

    # 8. key_concerns
    key_concerns = []
    if imaging_narrative.get("data_limitation"):
        key_concerns.append(imaging_narrative["data_limitation"])

    # 9. consultation_questions
    consultation_questions = [
        "缺少完整检验指标趋势数据，建议补充历次肿瘤标志物结果",
        "缺少用药方案记录，建议补充化疗/靶向治疗详细信息",
        "缺少病理报告，建议补充组织学类型和免疫组化结果",
    ]

    # 10. timeline
    timeline = []
    for item in all_items:
        if item.get("report_date"):
            timeline.append({
                "dates": [item.get("report_date", "")],
                "title": item.get("_source_file", ""),
                "category": item.get("report_type", ""),
                "note": "",
            })

    # 构建 report_context
    report_context = {
        "demographics": demographics,
        "files": files,
        "lab_trend": lab_trend,
        "imaging_summary": imaging_summary,
        "medication": medication,
        "genetic_highlights": genetic_highlights,
        "critical_alerts": critical_alerts,
        "key_concerns": key_concerns,
        "consultation_questions": consultation_questions,
        "timeline": timeline,
        "gaps": [
            "缺少完整检验指标趋势数据",
            "缺少用药方案记录",
            "缺少病理报告",
            "缺少患者基本信息",
        ],
    }

    manifest = {
        "demographics": demographics,
        "files": files,
        "categories_summary": {k: len(v) for k, v in groups.items()},
    }

    return manifest, report_context


def main():
    v2_output_dir = Path("/Users/qinxiaoqiang/Downloads/patient-record-organizer/temp_v2_output")
    profile_path = v2_output_dir / "profile.json"

    if not profile_path.exists():
        print(f"❌ 找不到 profile.json: {profile_path}")
        sys.exit(1)

    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    print(f"📋 读取 v2 profile: {profile.get('patient_id')}")

    manifest, report_context = build_manifest_from_profile(profile)

    # 生成 HTML
    output_path = Path("/Users/qinxiaoqiang/Downloads/patient-record-organizer/output/case_report_v2_test.html")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"🎨 生成 HTML 报告...")
    render_html_v2(
        manifest,
        timeline=report_context.get("timeline", []),
        output_path=output_path,
        extra={"extracted_texts": []},
        report_context=report_context,
    )

    print(f"✅ HTML 报告已生成: {output_path}")

    # 用浏览器打开
    import webbrowser
    webbrowser.open(f"file://{output_path}")
    print(f"🌐 已在浏览器中打开报告")


if __name__ == "__main__":
    main()
