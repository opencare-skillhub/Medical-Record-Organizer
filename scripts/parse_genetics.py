"""
基因检测解析（T4 扩展）

从文本中提取：
- 基因突变（EGFR 19del、ALK 融合等）
- 突变类型、点位、丰度（VAF）
- 药物敏感性（奥希替尼敏感等）
- PD-L1 表达、TMB 等免疫标志物
- 病理类型
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class GeneticHighlight:
    gene: str                       # 基因名
    mutation: str = ""              # 突变描述
    position: str = ""              # 点位（如 19del、G12D）
    vaf: Optional[float] = None     # 突变丰度（%）
    drug_sensitivity: str = ""      # 药物敏感性
    pathogenic: bool = False        # 是否致病
    immune_marker: str = ""         # 免疫标志物描述
    level: str = ""                 # 级别（info / highlight 等）
    abundance: str = ""             # 丰度描述
    breakthrough_type: str = ""     # 突破方式
    pathology_type: str = ""        # 病理类型
    notes: str = ""                 # 备注


def parse_genetics(text: str) -> List[GeneticHighlight]:
    """解析基因检测文本，返回 GeneticHighlight 列表"""
    highlights: List[GeneticHighlight] = []

    # EGFR
    if "EGFR" in text:
        egfr = GeneticHighlight(gene="EGFR", mutation="未知")
        if "19del" in text or "外显子19缺失" in text:
            egfr.position = "19del"
            egfr.mutation = "外显子19缺失突变"
            egfr.pathogenic = True
            if "奥希替尼" in text or "EGFR-TKI" in text:
                egfr.drug_sensitivity = "奥希替尼敏感"
        elif "L858R" in text or "858" in text:
            egfr.position = "L858R"
            egfr.mutation = "点突变"
            egfr.pathogenic = True
        highlights.append(egfr)

    # ALK
    if "ALK" in text:
        alk = GeneticHighlight(gene="ALK", mutation="未知")
        if "融合" in text and ("阴性" in text or "未检测到" in text):
            alk.mutation = "融合阴性"
            alk.pathogenic = True  # 融合阴性也是重要的病理信息
        elif "融合" in text:
            alk.mutation = "融合阳性"
            alk.pathogenic = True
        highlights.append(alk)

    # PD-L1
    if "PD-L1" in text or "PDL1" in text:
        pdl1 = GeneticHighlight(gene="PD-L1", mutation="表达", immune_marker="PD-L1 表达")
        m = re.search(r"TPS\s*[=：:]?\s*(\d+)%", text)
        if m:
            pdl1.position = f"TPS {m.group(1)}%"
            pdl1.immune_marker = f"PD-L1 TPS {m.group(1)}%"
        highlights.append(pdl1)

    # KRAS
    if "KRAS" in text:
        kras = GeneticHighlight(gene="KRAS", mutation="未知")
        if "G12D" in text:
            kras.position = "G12D"
            kras.mutation = "点突变"
        # KRAS 属于驱动基因库，无论野生型/突变都标记为 pathogenic
        kras.pathogenic = True
        highlights.append(kras)

    # UGT1A1 药物代谢
    if "UGT1A1" in text:
        ug = GeneticHighlight(gene="UGT1A1", mutation="未知", level="info")
        if "野生型" in text:
            ug.mutation = "野生型"
        elif "*6" in text or "*28" in text:
            ug.mutation = "多态性"
        highlights.append(ug)

    # 病理类型
    pathology_match = re.search(r"病理[结果]*[：:]\s*([\u4e00-\u9fa5]+(?:癌|瘤|淋巴瘤|肉瘤|增生|炎症))", text)
    if pathology_match:
        pt = GeneticHighlight(
            gene="病理类型",
            mutation="",
            pathology_type=pathology_match.group(1),
            level="info",
        )
        highlights.append(pt)

    # 通用 VAF / 丰度提取
    vaf_match = re.search(r"VAF\s*[=：:]?\s*([0-9]+(?:\.[0-9]+)?)\s*%?", text)
    vaf_str = vaf_match.group(1) if vaf_match else None

    # 突破方式
    breakthrough_match = re.search(r"(获得性耐药|继发耐药|靶向突破|免疫逃逸)", text)
    breakthrough_str = breakthrough_match.group(1) if breakthrough_match else None

    # 病理类型
    pathology_match = re.search(r"病理[结果]*[：:]\s*([\u4e00-\u9fa5]+(?:癌|瘤|淋巴瘤|肉瘤|增生|炎症))", text)
    pathology_str = pathology_match.group(1) if pathology_match else None

    # 将通用信息回填到已有 highlights
    for h in highlights:
        if vaf_str and not h.abundance:
            h.abundance = f"VAF {vaf_str}%"
            if h.vaf is None:
                h.vaf = float(vaf_str)
        if breakthrough_str and not h.breakthrough_type:
            h.breakthrough_type = breakthrough_str
        if pathology_str and h.gene == "病理类型" and not h.pathology_type:
            h.pathology_type = pathology_str

    # 若未创建病理类型条目但有匹配结果，补一条
    if pathology_str and not any(h.gene == "病理类型" for h in highlights):
        highlights.append(GeneticHighlight(
            gene="病理类型",
            mutation="",
            pathology_type=pathology_str,
            level="info",
        ))

    return highlights


def build_recent_focus(
    critical_alerts,
    highlights,
    timeline: List[dict],
    extra: Optional[List[dict]] = None,
) -> List[str]:
    """从危急值 + 时间线 + 基因检测结果中提取最近关注重点

    参数：
    - critical_alerts: 危急值列表（list[CriticalAlert] 或 list[dict]）
    - highlights: 基因检测高亮列表（list[GeneticHighlight] 或 list[dict]）
    - timeline: 时间线列表
    - extra: 额外关注点列表（可选）
    """
    focus: List[str] = []
    for a in critical_alerts:
        level = a.level if hasattr(a, "level") else a.get("level", 0)
        if level >= 4:
            name = a.item_name if hasattr(a, "item_name") else a.get("item_name", "")
            value = a.value if hasattr(a, "value") else a.get("value", "")
            unit = a.unit if hasattr(a, "unit") else a.get("unit", "")
            focus.append(f"⚠️ 危急值：{name} {value}{unit}")
    for h in highlights:
        pathogenic = h.pathogenic if hasattr(h, "pathogenic") else h.get("pathogenic", False)
        gene = h.gene if hasattr(h, "gene") else h.get("gene", "")
        position = h.position if hasattr(h, "position") else h.get("position", "")
        mutation = h.mutation if hasattr(h, "mutation") else h.get("mutation", "")
        drug_sensitivity = h.drug_sensitivity if hasattr(h, "drug_sensitivity") else h.get("drug_sensitivity", "")
        if pathogenic:
            focus.append(f"🧬 驱动突变：{gene} {position or mutation}")
        if drug_sensitivity:
            focus.append(f"💊 药物敏感性：{drug_sensitivity}")
    if timeline:
        last = timeline[-1] if isinstance(timeline, list) and timeline else {}
        if isinstance(last, dict):
            focus.append(f"📅 最近记录：{last.get('title', '')} ({last.get('dates', [''])[0]})")
    if extra:
        for item in extra:
            if isinstance(item, dict):
                focus.append(item.get("text", str(item)))
            else:
                focus.append(str(item))
    return focus


def build_consultation_questions(
    gaps: List[str],
    critical_alerts,
    highlights,
) -> List[str]:
    """基于当前数据生成 3-5 个咨询问题

    参数：
    - gaps: 信息缺口列表
    - critical_alerts: 危急值列表
    - highlights: 基因检测高亮列表
    """
    questions: List[str] = []
    for h in highlights:
        pathogenic = h.pathogenic if hasattr(h, "pathogenic") else h.get("pathogenic", False)
        drug_sensitivity = h.drug_sensitivity if hasattr(h, "drug_sensitivity") else h.get("drug_sensitivity", "")
        gene = h.gene if hasattr(h, "gene") else h.get("gene", "")
        position = h.position if hasattr(h, "position") else h.get("position", "")
        mutation = h.mutation if hasattr(h, "mutation") else h.get("mutation", "")
        gene_detail = f"{gene} {position or mutation}" if position or mutation else gene
        if pathogenic and not drug_sensitivity:
            questions.append(f"{gene_detail} 突变阳性，当前是否有对应靶向药？")
        if drug_sensitivity:
            questions.append(f"基于 {gene_detail} 药物敏感性（{drug_sensitivity}），一线方案如何选择？")
    for g in gaps:
        if "过敏" in g:
            questions.append("患者过敏史如何？是否影响当前方案？")
        if "化疗" in g:
            questions.append("最近一次化疗方案是什么？疗效如何？")
    if any(
        (a.level if hasattr(a, "level") else a.get("level", 0)) >= 4
        for a in (critical_alerts or [])
    ):
        questions.append("近期危急值如何处理？是否需要调整当前治疗？")
    if not questions:
        questions.append("当前治疗方案是否需要调整？")
    return questions[:5]


def format_genetic_highlights_md(highlights) -> str:
    """Markdown 格式（支持 list[GeneticHighlight] 或 list[dict]）"""
    if not highlights:
        return ""
    lines = ["# 基因与病理重点提示\n"]
    for h in highlights:
        if hasattr(h, "gene"):
            gene = h.gene
            position = h.position
            mutation = h.mutation
            pathogenic = h.pathogenic
            drug_sensitivity = h.drug_sensitivity
            vaf = h.vaf
            pathology_type = h.pathology_type
            immune_marker = h.immune_marker
        else:
            gene = h.get("gene", "")
            position = h.get("position", "")
            mutation = h.get("mutation", "")
            pathogenic = h.get("pathogenic", False)
            drug_sensitivity = h.get("drug_sensitivity", "")
            vaf = h.get("vaf")
            pathology_type = h.get("pathology_type", "")
            immune_marker = h.get("immune_marker", "")
        if gene == "病理类型" and pathology_type:
            line = f"- **病理类型**：{pathology_type}"
        elif immune_marker and "PD-L1" in (immune_marker or ""):
            line = f"- **{gene}**：{immune_marker}"
        else:
            line = f"- **{gene}**：{position or mutation}"
            if pathogenic:
                line += "（致病）"
            if drug_sensitivity:
                line += f"，药物敏感性：{drug_sensitivity}"
            if vaf:
                line += f"，VAF {vaf}%"
        lines.append(line)
    return "\n".join(lines)


def format_genetic_highlights_html(highlights) -> str:
    """HTML 格式（支持 list[GeneticHighlight] 或 list[dict]，输出 table 结构）"""
    if not highlights:
        return ""
    rows = []
    for h in highlights:
        if hasattr(h, "gene"):
            gene = h.gene
            position = h.position
            mutation = h.mutation
            pathogenic = h.pathogenic
            drug_sensitivity = h.drug_sensitivity
            vaf = h.vaf
            pathology_type = h.pathology_type
            immune_marker = h.immune_marker
        else:
            gene = h.get("gene", "")
            position = h.get("position", "")
            mutation = h.get("mutation", "")
            pathogenic = h.get("pathogenic", False)
            drug_sensitivity = h.get("drug_sensitivity", "")
            vaf = h.get("vaf")
            pathology_type = h.get("pathology_type", "")
            immune_marker = h.get("immune_marker", "")
        # 构建显示内容
        if gene == "病理类型" and pathology_type:
            display = pathology_type
        elif immune_marker and "PD-L1" in (immune_marker or ""):
            display = immune_marker
        else:
            parts = [position or mutation]
            if pathogenic:
                parts.append("（致病）")
            if drug_sensitivity:
                parts.append(f"药物敏感性：{drug_sensitivity}")
            if vaf:
                parts.append(f"VAF {vaf}%")
            display = "".join(parts)
        # HTML 转义 + 清理事件处理器
        gene_safe = _escape_and_clean(str(gene))
        display_safe = _escape_and_clean(str(display))
        row_class = ' style="color:#c83333;font-weight:700"' if pathogenic else ""
        rows.append(
            f"<tr{row_class}>"
            f"<td>{gene_safe}</td>"
            f"<td>{display_safe}</td>"
            f"</tr>"
        )
    return (
        '<table class="genetic-section" style="width:100%;border-collapse:collapse;border:1px solid #d7dce2;">'
        "<thead><tr><th>基因</th><th>详情</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        "</table>"
    )


def _escape_and_clean(text: str) -> str:
    """清理事件处理器属性并 HTML 转义，防止 XSS"""
    import html
    import re
    # 先移除常见事件处理器属性（onerror, onload, onclick 等）
    cleaned = re.sub(r'\s*on\w+\s*=\s*("[^"]*"|\'[^\']*\')', '', text)
    # 再转义 HTML 特殊字符
    cleaned = html.escape(cleaned, quote=True)
    return cleaned
