"""
v2 HTML 报告渲染器（D1）

职责：
- compute_report_context(): 把 v2 profile/groups 转换为 html-report-template.html 所需的 context
- render_html_report(): 用 Jinja2 渲染模板，输出 report.html

对应 dev/docs/template-context.md。
"""
from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    _JINJA2_AVAILABLE = True
except ImportError:
    _JINJA2_AVAILABLE = False


# 项目根目录
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_TEMPLATE_PATH = _PROJECT_ROOT / 'references' / 'html-report-template.html'

# 肿瘤标志物中文名 → 标准缩写
# 注意：LLM 有时输出"糖链抗原"（医院写法差异），统一归一化
_MARKER_ALIASES = {
    '癌胚抗原': 'CEA', 'cea': 'CEA',
    '糖类抗原19-9': 'CA199', '糖链抗原19-9': 'CA199',
    '糖类抗原19-9(高值)': 'CA199', '糖链抗原19-9(高值)': 'CA199',
    'ca199': 'CA199', 'ca19-9': 'CA199',
    '糖类抗原125': 'CA125', '糖链抗原125': 'CA125', 'ca125': 'CA125',
    '糖类抗原15-3': 'CA153', '糖链抗原15-3': 'CA153',
    '糖类抗原153': 'CA153', '糖链抗原153': 'CA153',
    'ca15-3': 'CA153', 'ca153': 'CA153',
    '糖类抗原724': 'CA724', '糖类抗原72-4': 'CA724',
    '糖链抗原724': 'CA724', '糖链抗原72-4': 'CA724',
    'ca724': 'CA724', 'ca72-4': 'CA724',
    '甲胎蛋白': 'AFP', 'afp': 'AFP',
    '前列腺特异性抗原': 'PSA', 'psa': 'PSA',
    '糖类抗原242': 'CA242', '糖链抗原242': 'CA242', 'ca242': 'CA242',
    '糖类抗原50': 'CA50', '糖链抗原50': 'CA50', 'ca50': 'CA50',
}


def _normalize_marker_text(name: str) -> str:
    """把医院常见写法差异（糖链→糖类，空格→无）归一化。"""
    if not name:
        return ''
    s = name.strip()
    if s.startswith('糖链'):
        s = '糖类' + s[2:]
    return s.lower()


def _standard_marker_name(name: str) -> str:
    """把中文标志物名映射为标准缩写。"""
    if not name:
        return ''
    name = _normalize_marker_text(name)
    if name in _MARKER_ALIASES:
        return _MARKER_ALIASES[name]
    for cn, std in _MARKER_ALIASES.items():
        if cn in name:
            return std
    # 英文缩写直接保留大写
    if name.isascii():
        return name.upper()
    return name


def _is_tumor_marker(name: str) -> bool:
    """判断是否为肿瘤标志物。"""
    std = _standard_marker_name(name)
    return std in {'CEA', 'CA199', 'CA125', 'CA153', 'CA724', 'AFP', 'PSA', 'CA242', 'CA50'}


def _format_change(current: Any, prev: Any) -> str:
    """计算变化格式：'↑ 50 (50%)' / '↓ 10 (5%)' / '—'。"""
    if current is None or prev is None:
        return '—'
    try:
        c = float(current)
        p = float(prev)
    except (ValueError, TypeError):
        return '—'
    if p == 0:
        return f'{"↑" if c > 0 else "↓"} {abs(c):.2f}'
    diff = c - p
    pct = abs(diff) / abs(p) * 100
    arrow = '↑' if diff > 0 else ('↓' if diff < 0 else '→')
    return f'{arrow} {abs(diff):.2f} ({pct:.0f}%)'


# ---------------------------------------------------------------------------
# 核心：compute_report_context
# ---------------------------------------------------------------------------
def compute_report_context(profile: Dict[str, Any], groups: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    """把 v2 profile + groups 转换为模板所需的 context dict。

    对应 dev/docs/template-context.md 中的所有变量。
    """
    all_items: List[Dict[str, Any]] = []
    for items in groups.values():
        if isinstance(items, list):
            all_items.extend(items)

    # ---- demographics ----
    demographics = {'name': '', 'gender': '', 'age': '', 'primary_diagnosis': '', 'icd_code': ''}
    for item in all_items:
        if item.get('report_type') == 'basic_info':
            demo = item.get('demographics') or {}
            if isinstance(demo, dict):
                demographics.update({
                    'name': demo.get('name', '') or '',
                    'gender': demo.get('gender', '') or '',
                    'age': demo.get('age', '') or '',
                })
                break
    # 从 diagnoses 补 primary_diagnosis
    for item in all_items:
        for diag in (item.get('diagnoses') or []):
            if isinstance(diag, dict) and diag.get('name'):
                demographics['primary_diagnosis'] = diag['name']
                demographics['icd_code'] = diag.get('icd10', '') or diag.get('stage', '') or ''
                break
        if demographics['primary_diagnosis']:
            break

    # ---- timeline ----
    _RT_LABELS = {
        'pathology': '病理报告', 'lab_results': '检验报告', 'imaging': '影像检查',
        'medication': '用药记录', 'clinical_records': '门诊/住院记录', 'basic_info': '基本信息',
    }
    timeline: List[Dict[str, Any]] = []
    for item in all_items:
        date = item.get('document_date') or item.get('report_date') or ''
        if not date:
            continue
        rt = item.get('report_type', '')
        # 更精确的标签：基因检测区别于普通病理
        if rt == 'pathology':
            label = '基因检测报告' if item.get('test_items') else '病理报告'
        else:
            label = _RT_LABELS.get(rt, item.get('_source_file', ''))
        note_parts = []
        # 优先用结论
        if item.get('conclusion'):
            note_parts.append(str(item['conclusion']))
        # 结构化 diagnoses
        for diag in (item.get('diagnoses') or []):
            if isinstance(diag, dict) and diag.get('name'):
                note_parts.append(f"诊断: {diag['name']}")
        # 关键突变摘要
        test_items = item.get('test_items') or []
        if test_items:
            genes_str = ', '.join(
                f"{g.get('gene_name','')} {g.get('detection_result','')}"[:40]
                for g in test_items[:6] if isinstance(g, dict)
            )
            if genes_str:
                note_parts.append(f"关键突变: {genes_str}")
        # CT 影像所见（裁短）
        findings = item.get('findings')
        if isinstance(findings, list):
            for f in findings:
                if isinstance(f, str) and len(f) > 10:
                    note_parts.append(f[:200])
        elif isinstance(findings, str) and len(findings) > 10:
            note_parts.append(findings[:200])
        note = '；'.join(note_parts)[:400]
        timeline.append({
            'dates': [date],
            'title': f"{date[:7]}: {label}",
            'category': rt,
            'note': note or '待添加',
        })
    timeline.sort(key=lambda x: x['dates'][0] if x['dates'] else '')

    # 去重：相同日期+类别+前80字摘要的去重
    seen = set()
    deduped = []
    for t in timeline:
        key = (t['dates'][0] if t['dates'] else '', t['category'], t['note'][:80])
        if key not in seen:
            seen.add(key)
            deduped.append(t)
    timeline = deduped

    # 时间线条目过多（>20），调用 LLM 精简为关键节点
    if len(timeline) > 20:
        timeline = _condense_timeline_with_llm(timeline, profile, groups)

    # ---- pathology ----
    pathology: List[Dict[str, Any]] = []
    for item in (groups.get('pathology') or []):
        date = item.get('document_date') or item.get('report_date') or '日期待确认'
        summary_parts = []
        findings = item.get('findings')
        if isinstance(findings, list):
            summary_parts.extend(str(f) for f in findings if f)
        elif isinstance(findings, str) and findings:
            summary_parts.append(findings)
        if item.get('conclusion'):
            summary_parts.append(str(item['conclusion']))
        # 兜底：取 report_summary 或 pathology_diagnosis 的文本作为摘要
        if not summary_parts:
            rs = item.get('report_summary')
            if rs:
                summary_parts.append(str(rs)[:300])
        if not summary_parts:
            pd = item.get('pathology_diagnosis')
            if isinstance(pd, str):
                summary_parts.append(pd[:300])
        # 取第一条 test_item 作为快照
        test_items = item.get('test_items')
        if not summary_parts and test_items:
            genes = [f"{ti.get('gene_name','')}: {ti.get('detection_result','')}"[:60]
                     for ti in test_items[:3] if isinstance(ti, dict)]
            if genes:
                summary_parts.append('; '.join(genes))
        pathology.append({
            'label': item.get('_source_file', ''),
            'type': item.get('specimen_type', '') or '病理',
            'date': date,
            'summary': '；'.join(summary_parts) or '待添加',
            'findings': findings or [],
            'value': '',
            'is_critical': False,
        })

    # ---- 病理兜底：无结构化数据时从原文读取 ----
    if not any(p.get('findings') for p in pathology) and (groups.get('pathology') or []):
        for item in (groups.get('pathology') or []):
            fname = item.get('_source_file', '')
            src_dir = Path(profile.get('output_dir', '')) / 'sanitized' / fname
            if src_dir and src_dir.exists():
                raw = src_dir.read_text(encoding='utf-8')
                # 找病理诊断关键行
                import re
                diag_match = re.search(r'病理诊断[：:].*?(?=\n\n|\Z)', raw, re.DOTALL)
                if diag_match:
                    for p in pathology:
                        if p['label'] == fname:
                            p['summary'] = diag_match.group(0).strip()[:300]
                            p['value'] = raw[:500]
                            break

    # ---- genetic_highlights ----
    # 展示所有真正有突变的基因（排除野生型/良性/未检出）
    # 分类：体细胞突变 / 胚系突变 / 药敏基因，level表示层级
    _BENIGN_WORDS = {'野生型', '野生', 'wild', '无突变', '阴性', '未检测到', '未检出',
                     '阴性正常', '(-)', 'no mutation', 'not detected', '正常'}
    genetic_highlights: List[Dict[str, Any]] = []

    # 1. 基因突变：仅从病理组(基因检测报告)中提取，必须有 entity_name
    #    不混入 clinical 记录中的手工提取/文本提及
    _all_gene_items = list(groups.get('pathology') or [])  # 仅病理组，不混 clinical
    _gene_seen = set()
    for item in _all_gene_items:
        for gene in (item.get('test_items') or []):
            if not isinstance(gene, dict):
                continue
            gene_name = (gene.get('gene_name') or '').strip()
            result = gene.get('detection_result', '') or gene.get('result', '') or ''

            # 必须有基因名（排除手工提取的文本碎片如"ATM突变-致癌原因..."）
            if not gene_name:
                continue

            key = f"{gene_name}|{result[:40]}"
            if key in _gene_seen:
                continue
            _gene_seen.add(key)

            # 跳过良性/野生型/正常/未检出
            if any(w in result for w in _BENIGN_WORDS):
                continue
            # 跳过无明显突变描述的空条目
            if len(result.strip()) < 3:
                continue

            tier = (gene.get('evidence_tier') or '').strip().upper()
            tier_label = {'1A': 'I类', '1B': 'I类', '2A': 'II类', '2B': 'II类', '3': 'III类'}.get(tier, tier)
            is_path = gene.get('is_pathogenic')
            category = gene.get('category', '') or '体细胞'
            abundance = gene.get('abundance', '')

            # 是否有突变信号
            has_mutation = is_path is True or tier or abundance or any(
                w in result.lower() for w in ('突变', '致病', '移码', '缺失', '插入', '无义', '扩增', '重排')
            )
            if not has_mutation:
                continue

            significance = 'pathogenic' if (is_path is True or tier in ('1A','1B','2A','2B')) else 'mutation'

            genetic_highlights.append({
                'category': 'gene',
                'gene': gene.get('gene_name', ''),
                'marker': gene.get('gene_name', ''),
                'mutation': result,
                'result': result,
                'pathogenic': is_path,
                'significance': significance,
                'is_critical': significance == 'pathogenic',
                'abundance': abundance,
                'evidence_tier': tier,
                'tier_label': tier_label,
                'tags': [f'{"胚系" if "胚系" in category or "germline" in category.lower() else "体细胞"}{"突变" if significance=="mutation" else "致病"}'] if category else [],
            })

    # 2. 药敏基因单独板块（pharmacogenomics: UGT1A1, DPYD等）
    _CHEMO_GENES = {'UGT1A1', 'DPYD', 'ERCC1', 'XRCC1', 'GSTP1', 'NQO1', 'MTHFR', 'CYP2D6', 'CYP3A4'}
    pg_seen = set()
    for item in (_all_gene_items):
        for pg in (item.get('pharmacogenomics') or []):
            if not isinstance(pg, dict):
                continue
            gene = pg.get('gene', '')
            key = f"{gene}|{pg.get('genotype','')}"
            if key in pg_seen:
                continue
            pg_seen.add(key)
            if gene.upper() in _CHEMO_GENES or any(g in gene.upper() for g in _CHEMO_GENES):
                genotype = pg.get('genotype', '') or pg.get('variant', '')
                risk = pg.get('risk', '') or pg.get('recommendation', '')
                drug = pg.get('drug', '')
                genetic_highlights.append({
                    'category': 'pgx',
                    'gene': gene,
                    'marker': gene,
                    'mutation': genotype,
                    'result': genotype,
                    'pathogenic': False,
                    'significance': 'drug',
                    'is_critical': False,
                    'abundance': '',
                    'evidence_tier': '',
                    'tier_label': drug or '药敏',
                    'tags': [risk] if risk else [],
                })

    # 排序：致病 > 有等级突变 > VUS > 药敏
    _SIG_ORDER = {'pathogenic': 0, 'mutation': 1, 'drug': 2}
    genetic_highlights.sort(key=lambda x: _SIG_ORDER.get(x.get('significance', ''), 99))

    # ---- genetic_highlights 兜底：LLM 返回空时用 parse_genetics 从原文提取 ----
    if not genetic_highlights and (groups.get('pathology') or []):
        from scripts.parse_genetics import parse_genetics
        combined = ''
        for item in (groups.get('pathology') or []):
            fname = item.get('_source_file', '')
            src_dir = Path(profile.get('output_dir', '')) / 'sanitized' / fname
            if src_dir and src_dir.exists():
                combined += '\n' + src_dir.read_text(encoding='utf-8')
        if combined:
            highlights = parse_genetics(combined)
            for h in highlights:
                genetic_highlights.append({
                    'category': 'gene', 'gene': h.gene,
                    'marker': h.gene, 'mutation': h.mutation or h.position,
                    'result': h.mutation or h.position,
                    'pathogenic': h.pathogenic,
                    'is_critical': h.pathogenic,
                    'abundance': h.abundance or '',
                    'evidence_tier': '',
                    'tier_label': '',
                    'tags': [h.drug_sensitivity] if h.drug_sensitivity else [],
                })

    # ---- medication ----
    medication_summary: List[Dict[str, Any]] = []
    medication_table: List[Dict[str, Any]] = []
    med_tl = profile.get('medication_timeline') or {}
    seen_meds: set = set()
    _MED_CHEMO = {'吉西他滨', '紫杉醇', '白蛋白紫杉醇', '氟尿嘧啶', '奥沙利铂', '伊立替康',
                  '卡培他滨', '多西他赛', '顺铂', '卡铂', '培美曲塞', '环磷酰胺'}

    def _is_chemo(name: str) -> bool:
        for kw in _MED_CHEMO:
            if kw in name:
                return True
        return False

    def _add_med(name: str, dose: str = '', route: str = '', purpose: str = '', is_chemo: bool = False) -> None:
        if not name:
            return
        key = (name.strip().lower(), str(dose).strip())
        if key in seen_meds:
            return
        seen_meds.add(key)
        medication_summary.append({'label': name, 'value': dose, 'is_critical': is_chemo})
        medication_table.append({'name': name, 'dose': dose, 'route': route, 'purpose': purpose or ('化疗' if is_chemo else '')})

    # 主来源：medication_timeline
    for med in (med_tl.get('timeline') or []):
        _add_med(
            med.get('name', '') or med.get('drug', ''),
            med.get('dosage') or med.get('dose', '') or '',
            med.get('route', ''),
            med.get('purpose', '') or med.get('type', ''),
            _is_chemo(med.get('name', '') or med.get('drug', '')),
        )

    # 补充：从 clinical 和 medication 组的 medications 字段
    for grp_key in ('clinical', 'medication'):
        for item in (groups.get(grp_key) or []):
            for m in (item.get('medications') or []):
                if isinstance(m, dict):
                    _add_med(
                        m.get('name', '') or m.get('drug', ''),
                        m.get('dosage') or m.get('dose', '') or '',
                        m.get('route', ''),
                        m.get('purpose', '') or m.get('type', ''),
                        _is_chemo(m.get('name', '') or m.get('drug', '')),
                    )
                elif isinstance(m, str):
                    _add_med(m, '')

    # 兜底：从 sanitized 原文正则提取剂量（LLM 常漏剂量字段），但不新增药物条目
    if any(not t['dose'] for t in medication_table):
        import re as _re
        for item in (groups.get('clinical') or []) + (groups.get('medication') or []):
            fname = item.get('_source_file', '')
            src = Path(profile.get('output_dir', '')) / 'sanitized' / fname
            if not src.exists():
                continue
            raw = src.read_text(encoding='utf-8')
            # 对已有药物表中的每个空缺剂量，从原文匹配补充
            for i, med in enumerate(medication_table):
                if med['dose']:
                    continue
                name = med['name']
                # 取药物名的关键标识词（括号前的主名或品牌名后的主成分）
                key_words = name.split('(')[0].strip() if '(' in name else name
                if len(key_words) < 4:
                    continue
                # 在原文中找 "关键名 + 剂量数字 + 单位" 模式的文本
                escaped = _re.escape(key_words[:15])
                m = _re.search(rf'{escaped}\s*.*?(\d+[.,\d]*\s*(?:g|mg|ml)\s*(?:[×xX*]\s*\d+[.,\d]*\s*(?:支|瓶|袋))?)', raw)
                if m:
                    dose = m.group(1).strip()
                    medication_table[i]['dose'] = dose
                    medication_summary[i]['value'] = dose
                # 如果有给药方式也补上
                route_m = _re.search(rf'{escaped}.*?(静滴|静推|口服|肌注)', raw)
                if route_m and not medication_table[i]['route']:
                    medication_table[i]['route'] = route_m.group(1)

    # 去重：同名药保留有剂量的版本
    deduped: Dict[str, Dict[str, str]] = {}
    for m in medication_table:
        name = m.get('name', '').strip()
        # 忽略氯化钠/输液载体
        if not name or len(name) < 4 or '氯化钠' in name or '辰欣' in name or '双鹤' in name:
            continue
        key = name.split('(')[0].strip()  # 用主名去重
        if key not in deduped or (m.get('dose') and not deduped[key].get('dose')):
            deduped[key] = m
        elif m.get('dose') and deduped[key].get('dose') and m['dose'] != deduped[key]['dose']:
            deduped[key + ' (另)]'] = m
    medication_table = list(deduped.values())
    # 同步过滤 medication_summary
    table_names = {m['name'] for m in medication_table}
    medication_summary = [m for m in medication_summary if m.get('label', '').strip() and '氯化钠' not in m.get('label', '')]

    medication_prescription_date = ''
    if med_tl.get('timeline'):
        medication_prescription_date = med_tl['timeline'][0].get('start_date', '') or ''

    # ---- imaging_summary ----
    imaging_summary: List[Dict[str, Any]] = []
    for item in (groups.get('imaging') or []):
        date = item.get('document_date') or item.get('report_date') or ''
        if not date:
            # 从原始文件名推断日期（脱敏映射中保留了原始文件名的日期信息）
            fname = item.get('_source_file', '')
            import re
            m = re.search(r'(\d{4}-\d{2}-\d{2})', fname)
            if not m:
                m = re.search(r'(\d{4})\D?(\d{2})\D?(\d{2})', fname)
            if m:
                date = f'{m.group(1)}-{m.group(2)}-{m.group(3)}' if m.lastindex and m.lastindex >= 3 else m.group(1)
        if not date:
            date = '—'
        findings = item.get('findings')
        if isinstance(findings, list):
            findings_text = '；'.join(str(f) for f in findings if f)
        elif isinstance(findings, str):
            findings_text = findings
        else:
            findings_text = item.get('conclusion', '') or ''
        imaging_summary.append({
            'date': date,
            'modality': item.get('modality', '') or _infer_modality(item.get('_source_file', '')),
            'findings': findings_text,
        })
    # 从 imaging_narrative 补充
    img_narr = profile.get('imaging_narrative') or {}
    if img_narr.get('primary_lesion_timeline') and not imaging_summary:
        imaging_summary.append({
            'date': '综合',
            'modality': '影像演变',
            'findings': str(img_narr['primary_lesion_timeline']),
        })

    # ---- tumor_marker_tables + lab_trend + chart_svg ----
    lab_trends = profile.get('lab_trends') or {}
    tumor_marker_tables: Dict[str, Any] = {}
    lab_trend_rows: List[Dict[str, Any]] = []

    all_dates = set()
    indicator_to_std: Dict[str, str] = {}
    for indicator in lab_trends:
        std = _standard_marker_name(indicator)
        indicator_to_std[indicator] = std
        for row in lab_trends[indicator].get('trend', []):
            all_dates.add(row.get('date', ''))
    all_dates = sorted(d for d in all_dates if d)

    # tumor_marker_tables
    for indicator, data in lab_trends.items():
        if not _is_tumor_marker(indicator):
            continue
        std_name = indicator_to_std[indicator]
        unit = data.get('unit', '')
        ref = data.get('ref_range')
        if isinstance(ref, (list, tuple)) and len(ref) == 2:
            ref_range_str = f'{ref[0]}–{ref[1]} {unit}'.strip()
        else:
            ref_range_str = ''
        rows = []
        prev_val = None
        for tr in data.get('trend', []):
            val = tr.get('value')
            rows.append({
                'date': tr.get('date', ''),
                'value': val,
                'change': _format_change(val, prev_val),
                'fluctuation': tr.get('fluctuation', ''),
                'note': tr.get('note', ''),
                'is_abnormal': bool(tr.get('abnormal')),
            })
            prev_val = val
        tumor_marker_tables[std_name] = {
            'unit': unit,
            'ref_range': ref_range_str,
            'rows': rows,
        }

    # lab_trend（旧格式兜底：每行一个日期，每列一个指标）
    for date in all_dates:
        row = {'date': date}
        for indicator in lab_trends:
            std = indicator_to_std[indicator]
            for tr in lab_trends[indicator].get('trend', []):
                if tr.get('date') == date:
                    row[std] = tr.get('value', '')
                    break
        lab_trend_rows.append(row)

    # ---- 通用检验指标表（非肿瘤标志物 + 单日期场景兜底） ----
    lab_flat: List[Dict[str, Any]] = []
    for indicator, data in lab_trends.items():
        if _is_tumor_marker(indicator):
            continue  # 肿瘤标志物已在 tumor_marker_tables 里
        trend = data.get('trend', [])
        if trend:
            # 取最新一条（trend 已按日期升序排列，取最后一个）
            tr = trend[-1]
            lab_flat.append({
                'name': indicator,
                'value': tr.get('value', ''),
                'unit': tr.get('unit', ''),
                'date': tr.get('date', ''),
                'abnormal': bool(tr.get('abnormal')),
            })

    # ---- 检验分区与异常卡片 ----
    _LAB_CATEGORIES = {
        '肿瘤标志物': {'CEA','CA199','CA125','CA724','CA242','CA50','CA153','AFP','PSA','糖类抗原','糖链抗原','癌胚抗原'},
        '肝功能': {'ALT','AST','GGT','ALP','TBIL','DBIL','IBIL','TP','ALB','GLB','A/G','前白蛋白','甘胆酸','LDH','总胆红素','直接胆红素','白蛋白','转氨酶'},
        '肾功能': {'CREA','BUN','UREA','UA','eGFR','肌酐','尿素','尿酸','肾小球'},
        '血常规': {'WBC','RBC','Hb','HCT','PLT','NEU','LYM','MONO','EO','BASO','白细胞','红细胞','血红蛋白','血小板','中性粒','淋巴'},
        '电解质': {'K','Na','Cl','Ca','P','Mg','钾','钠','氯','钙','磷','镁','碳酸氢根'},
        '血脂血糖': {'TG','TC','HDL','LDL','GLU','血糖','甘油三酯','总胆固醇','脂蛋白','sd-LDL'},
        '凝血功能': {'PT','APTT','INR','D-二聚体','纤维蛋白原','FIB','TT'},
        '其他': set(),
    }

    def _classify_lab(name: str) -> str:
        upper = name.upper()
        for cat, keywords in _LAB_CATEGORIES.items():
            for kw in keywords:
                if kw in upper or kw in name:
                    return cat
        return '其他'

    # 指标分类
    categorized: Dict[str, List[Dict[str, Any]]] = {}
    for indicator, data in lab_trends.items():
        cat = _classify_lab(indicator)
        categorized.setdefault(cat, [])
        for tr in data.get('trend', []):
            categorized[cat].append({
                'name': indicator, 'value': tr.get('value',''), 'unit': tr.get('unit',''),
                'date': tr.get('date',''), 'abnormal': bool(tr.get('abnormal', False)),
                'flag': tr.get('flag',''), 'ref_low': data.get('ref_range',(None,None))[0] if isinstance(data.get('ref_range'), (tuple, list)) else None,
                'ref_high': data.get('ref_range',(None,None))[1] if isinstance(data.get('ref_range'), (tuple, list)) else None,
            })
            break
    # 去掉空分类
    categorized = {k: v for k, v in categorized.items() if v and k != '其他'}
    # 异常指标抢眼展示（卡片格式）
    lab_abnormal: List[Dict[str, Any]] = []
    for items in categorized.values():
        for it in items:
            if it['abnormal']:
                lab_abnormal.append(it)
    categorized_lab = [{'category': k, 'items': v} for k, v in categorized.items()]

    # ---- lab_analysis_conclusion (检验分析结论) ----
    lab_analysis_conclusion = ''
    for item in (groups.get('lab') or []):
        if item.get('lab_analysis_conclusion'):
            lab_analysis_conclusion = item['lab_analysis_conclusion']
            break

    # ---- clinical_summary (临床摘要) ----
    # 选择最可信的临床摘要：优先取 timeline_items 最多的记录，
    # 避免单页碎片化的 LLM 捏造（如捏造黄疸/肝转移/错误日期）
    clinical_summary = ''
    best_tl_len = 0
    for item in (groups.get('clinical') or []):
        cs = item.get('clinical_summary') or ''
        tl = len(item.get('timeline_items') or [])
        # 取 timeline_items 最多的那一条（通常是完整病情概述文档）
        if cs and tl >= best_tl_len:
            best_tl_len = tl
            clinical_summary = cs

    # ---- pathology_diagnosis (病理诊断要点) ----
    pathology_diagnosis: Optional[Dict[str, Any]] = None
    for item in (groups.get('pathology') or []):
        pd = item.get('pathology_diagnosis')
        if pd:
            # LLM 有时返回 list/str 而非 dict
            if isinstance(pd, list):
                # 列表取第一个 dict 元素
                for e in pd:
                    if isinstance(e, dict):
                        pd = e
                        break
                else:
                    logger.warning('pathology_diagnosis 为 list 且无 dict 元素，跳过')
                    continue
            if isinstance(pd, str):
                # 字符串格式 "胰腺穿刺标本，查见肿瘤，建议免疫组化协助分析"
                # 构建最小 dict
                logger.info('pathology_diagnosis 为 str，转换为 dict: %s', pd[:80])
                pd_dict: Dict[str, Any] = {'pathology_diagnosis': pd}
                # 尝试从原文中提取更多字段
                raw_text = ' '.join([d.get('summary', '') or '' for d in (item.get('findings') or [])])
                if 'T' in raw_text.upper() and 'N' in raw_text.upper() and 'M' in raw_text.upper():
                    import re
                    tnm = re.search(r'(T\d[ab]?N\d[ab]?M\d[ab]?)', raw_text)
                    if tnm:
                        pd_dict['tnm_stage'] = tnm.group(1)
                pd = pd_dict
            if isinstance(pd, dict):
                pathology_diagnosis = pd
                break
            logger.warning('pathology_diagnosis 非 dict/str/list (type=%s)，跳过', type(pd).__name__)

    # ---- ihc_markers (免疫组化) ----
    ihc_items: List[Dict[str, Any]] = []
    # 主来源：pathology 组的 ihc_markers
    for item in (groups.get('pathology') or []):
        for m in (item.get('ihc_markers') or []):
            if isinstance(m, dict):
                ihc_items.append(m)
    # 补充来源：clinical 组也包含部分 IHC 数据（如病情概述混合文档）
    for item in (groups.get('clinical') or []):
        for m in (item.get('ihc_markers') or []):
            if isinstance(m, dict):
                seen = {(i.get('marker'), i.get('result')) for i in ihc_items}
                if (m.get('marker'), m.get('result')) not in seen:
                    ihc_items.append(m)
    # 兜底：LLM 未提取免疫组化时，从 sanitized 原文正则提取
    if not ihc_items and (groups.get('pathology') or []):
        import re
        _IHC_PATTERN = re.compile(
            r'(CK\d*|CD\d+|CDX2|SATB2|P40|P53|TTF-?1|Napsin\s*A|NapsinA|'
            r'Ki-?67(?:\([^)]+\))?|SMAD4|Her-?2|HER-?2|ER|PR|AR|Vimentin|VIM|EMA|'
            r'CgA|Syn|SMA|Desmin|MSH2|MSH6|MLH1|PMS2|S100|MUC\d*|'
            r'PD-?L1|CK7|CK19|CK20|CA19-9|GATA3|PAX8|CD3|CD4|CD8|CD20|CD68|CD163|FoxP3|'
            r'CAM5\.2|CA125|BCL2|BCL6|MUM1|c-?MYC|ALK|ROS1|BRAF|MUC4|'
            r'MUC5AC|CEA|E-?cadherin|EMA|CKAE1/AE3|CK8/18|DOG1|'
            r'CD34|CD31|CD117|CD56|CD138|CD38|CD5|CD10|CD30|'
            r'CD79a|PAX5|TdT|MPO|CD15|CD99|SOX-?10|SOX10|'
            r'HMB-?45|Melan-?A|SMA|SMMS-1|Calretinin|Caldesmon)'
            r'\s*[\(（]?[\s]*[-+±%0-9.]+[\s]*[\)）]?',
            re.IGNORECASE
        )
        _IHC_LINE = re.compile(
            r'(CK\d*|CD\d+|CDX2|Ki-?67|PD-?L1|CK7|CK19|P53|P40|TTF-?1|'
            r'HER-?2|ER|PR|SMA|Desmin|CgA|Syn)\s*[：:(（]\s*([-+±%0-9a-zA-Z]+)\s*[)）]',
            re.IGNORECASE
        )
        for item in (groups.get('pathology') or []):
            fname = item.get('_source_file', '')
            src = Path(profile.get('output_dir', '')) / 'sanitized' / fname
            if src.exists():
                raw = src.read_text(encoding='utf-8')
                for m in _IHC_LINE.finditer(raw):
                    ihc_items.append({
                        'marker': m.group(1).strip(),
                        'result': m.group(2).strip(),
                    })
                for m in _IHC_PATTERN.finditer(raw):
                    name = m.group(1).strip()
                    existing = set(i['marker'] for i in ihc_items)
                    if name not in existing:
                        ihc_items.append({
                            'marker': name,
                            'result': m.group(0)[len(name):].strip('(（）) '),
                        })

    # ---- pd_l1 ----
    pd_l1: Optional[Dict[str, Any]] = None
    for item in (groups.get('pathology') or []):
        pl = item.get('pd_l1')
        if pl:
            if not isinstance(pl, dict):
                logger.warning('pd_l1 非 dict (type=%s)，跳过: %s', type(pl).__name__, str(pl)[:100])
                continue
            pd_l1 = pl
            break

    # ---- timeline_items (临床时间轴) ----
    # ---- timeline_items (临床时间轴) ----
    # 仅取 timeline_items 最多的一条 clinical 记录作为权威时间轴
    # 不混入其他来源、不合并碎片，避免重复和 LLM 幻觉污染
    timeline_items: List[Dict[str, Any]] = []
    _TL_CUTOFF = '2026-01-01'

    best_tl: List[Dict[str, Any]] = []
    for item in (groups.get('clinical') or []):
        tl = item.get('timeline_items') or []
        if len(tl) > len(best_tl):
            best_tl = tl

    if best_tl:
        for t in best_tl:
            if isinstance(t, dict):
                date = t.get('date', '') or ''
                if date and date <= _TL_CUTOFF:
                    timeline_items.append(t)
        timeline_items.sort(key=lambda x: x.get('date', '') or '')

    # chart_svg_ca199（保留兼容）
    chart_svg_ca199 = ''
    chart_svg = ''
    if 'CA199' in tumor_marker_tables:
        chart_svg_ca199 = _generate_marker_svg(tumor_marker_tables['CA199'])
        chart_svg = chart_svg_ca199

    # 多指标趋势图（归一化 + 绝对值 + 同步性告警）
    from scripts.render_html import (
        _generate_multi_marker_svg,
        _generate_absolute_multi_svg,
        _analyze_marker_synchronization,
    )
    chart_svg_normalized = _generate_multi_marker_svg(tumor_marker_tables)
    chart_svg_absolute = _generate_absolute_multi_svg(tumor_marker_tables)
    marker_sync_alert = _analyze_marker_synchronization(tumor_marker_tables)

    # ---- critical_alerts ----
    critical_alerts: List[Dict[str, Any]] = []
    lab_analysis = profile.get('lab_analysis') or {}
    for indicator, analysis in lab_analysis.items():
        level = analysis.get('alert_level', 'normal')
        if level == 'critical':
            critical_alerts.append({
                'item_name': indicator,
                'message': analysis.get('clinical_inference', '') or f'{indicator} 指标危急',
                'level': 5,
                'emoji': '🔴',
                'action': '建议立即联系主治医生',
            })
    # 补充异常检验值
    for indicator, data in lab_trends.items():
        for tr in data.get('trend', []):
            if tr.get('abnormal') and _is_tumor_marker(indicator):
                std = indicator_to_std.get(indicator, indicator)
                if not any(a['item_name'] == std for a in critical_alerts):
                    critical_alerts.append({
                        'item_name': std,
                        'message': f'{std}: {tr.get("value", "")} {tr.get("unit", "")}（异常）',
                        'level': 3,
                        'emoji': '🟡',
                        'action': '下次就诊告知医生',
                    })
    has_critical = any(a['level'] >= 4 for a in critical_alerts)

    # ---- key_concerns ----
    priority_labels = {'high': '高', 'medium': '中', 'low': '低'}
    key_concerns: List[Any] = []
    mdt_analysis = profile.get('mdt_analysis') or {}
    mdt_concerns = mdt_analysis.get('concerns') or []
    if mdt_concerns:
        for item in mdt_concerns:
            if isinstance(item, dict):
                priority = item.get('priority') or 'medium'
                key_concerns.append({
                    'text': item.get('title') or item.get('analysis') or '',
                    'analysis': item.get('analysis') or '',
                    'priority': priority,
                    'priority_label': priority_labels.get(priority, '中'),
                    'disciplines': item.get('disciplines') or ([item.get('discipline')] if item.get('discipline') else []),
                    'suggested_direction': item.get('suggested_direction') or '',
                })
            else:
                key_concerns.append({'text': str(item), 'priority': 'medium'})
    else:
        # MDT 不可用时，基于数据生成有意义的问题摘要而非原始检验值列表
        concerns_generated = []

        # 1. 肿瘤标志物异常趋势分析
        tumor_alerts = []
        for name, mdata in (tumor_marker_tables or {}).items():
            rows = mdata.get('rows', [])
            if len(rows) >= 2:
                first_v = rows[0].get('value')
                last_v = rows[-1].get('value')
                try:
                    if float(first_v or 0) > 0 and float(last_v or 0) > 0:
                        change_pct = (float(last_v) - float(first_v)) / float(first_v) * 100
                        if abs(change_pct) > 20:
                            direction = '下降' if change_pct < 0 else '上升'
                            tumor_alerts.append(f"{name}: 从{first_v}→{last_v} ({direction}{abs(change_pct):.0f}%)")
                except (ValueError, TypeError):
                    continue
        if tumor_alerts:
            concerns_generated.append({
                'text': '肿瘤标志物变化趋势',
                'analysis': '、'.join(tumor_alerts[:5]),
                'priority': 'high',
                'priority_label': '高',
                'disciplines': ['肿瘤科'],
                'suggested_direction': '结合影像检查评估疗效，若持续上升需排查进展',
            })

        # 2. 基因检测致病突变
        pathogenic_genes = [g for g in genetic_highlights if g.get('significance') == 'pathogenic']
        if pathogenic_genes:
            pg_names = [g['gene'] for g in pathogenic_genes[:5]]
            concerns_generated.append({
                'text': f'致病性基因突变: {", ".join(pg_names)}',
                'analysis': f'检测到{len(pathogenic_genes)}个致病性基因突变，需关注靶向/免疫治疗机会及家族遗传风险',
                'priority': 'high',
                'priority_label': '高',
                'disciplines': ['肿瘤科', '遗传咨询'],
                'suggested_direction': '评估靶向药物匹配及胚系遗传检测',
            })

        # 3. 肝功能异常
        liver_abnormal = [a for a in (lab_abnormal or []) if a.get('name', '') in ('ALT', 'AST', 'GGT', 'TBIL', 'DBIL')]
        if liver_abnormal:
            items = ', '.join(f"{a['name']}={a['value']}" for a in liver_abnormal[:5])
            concerns_generated.append({
                'text': f'肝功能指标异常',
                'analysis': items,
                'priority': 'medium',
                'priority_label': '中',
                'disciplines': ['肿瘤科', '消化科'],
                'suggested_direction': '排查化疗药物性肝损伤或胆道梗阻',
            })

        # 4. 用药方案复杂度
        if len(medication_table) >= 3:
            concerns_generated.append({
                'text': '多线化疗方案更替',
                'analysis': f'已使用{len(medication_table)}种药物，经历多次方案调整，需关注耐药性和累积毒性',
                'priority': 'medium',
                'priority_label': '中',
                'disciplines': ['肿瘤科'],
                'suggested_direction': '评估化疗敏感性变化及后续治疗方案选择',
            })

        if concerns_generated:
            key_concerns = concerns_generated
        else:
            # 真正的兜底
            for a in critical_alerts[:3]:
                key_concerns.append({'text': a.get('message', ''), 'priority': 'low', 'analysis': '', 'priority_label': '低'})

    # ---- consultation_questions ----
    # 从 MDT 分析中获取 LLM 生成的咨询建议，失败时基于数据异常动态生成
    mdt_analysis = profile.get('mdt_analysis') or {}
    consultation_questions = mdt_analysis.get('consultation_questions') or []
    if not consultation_questions:
        q = []

        # 基于实际异常发现生成问诊建议
        if tumor_marker_tables:
            # 找出趋势异常的标志物
            rising = []
            falling = []
            for name, mdata in tumor_marker_tables.items():
                rows = mdata.get('rows', [])
                if len(rows) >= 2:
                    try:
                        first_v = float(rows[0].get('value', 0) or 0)
                        last_v = float(rows[-1].get('value', 0) or 0)
                        if first_v > 0:
                            pct = (last_v - first_v) / first_v * 100
                            if pct > 20: rising.append(f'{name}(+{pct:.0f}%)')
                            elif pct < -20: falling.append(f'{name}({pct:.0f}%)')
                    except (ValueError, TypeError): continue
            if rising:
                q.append(f'{"、".join(rising)}持续上升，需向医生确认是否提示疾病进展？是否需调整治疗方案？')
            if falling:
                q.append(f'{"、".join(falling)}呈下降趋势，需确认当前治疗是否持续有效？')

        abnormal_markers = [a for a in (lab_abnormal or []) if a.get('name') in ('ALT','AST','GGT','TBIL','CREA','WBC','PLT','Hb')]
        if abnormal_markers:
            items = '、'.join(f"{a['name']}={a['value']}" for a in abnormal_markers[:4])
            q.append(f'检查发现肝功能/血常规异常（{items}），需向医生确认是否需调整化疗方案或加用保肝/升白药物？')

        if genetic_highlights:
            path_genes = [g for g in genetic_highlights if g.get('significance') == 'pathogenic']
            if path_genes:
                q.append(f'检测到{",".join(g["gene"] for g in path_genes[:3])}致病突变，需向医生确认是否影响靶向/免疫治疗选择？家属是否需遗传咨询？')

        if len(medication_table) >= 5:
            q.append(f'已使用多线化疗（{len(medication_table)}种药物），需向医生了解目前耐药性情况及后续治疗备选方案')

        if not q:
            # 兜底：基础建议
            if not imaging_summary: q.append('建议补充历次影像检查报告（CT/MRI/PET-CT），以对照评估病灶变化')
            if not tumor_marker_tables: q.append('建议补充历次肿瘤标志物结果以完善趋势分析')
            if not medication_table: q.append('建议补充用药方案详细信息（药物、剂量、周期）')
            if not pathology_diagnosis: q.append('建议补充病理报告（组织学类型、TNM分期、免疫组化）')
        if q:
            consultation_questions = q[:5]
        else:
            consultation_questions = ['根据现有资料，病情档案已较为完整。建议线下就诊时携带全部检查资料。']

    # ---- files ----
    files: List[Dict[str, Any]] = []
    for item in all_items:
        files.append({
            'title': item.get('_source_file', ''),
            'date': item.get('document_date') or item.get('report_date') or '日期待确认',
            'category': item.get('report_type', '未分类'),
        })

    # ---- gaps ----
    gaps: List[str] = []
    if not lab_trends:
        gaps.append('缺少检验指标趋势数据')
    if not med_tl.get('timeline'):
        gaps.append('缺少用药方案记录')
    if not pathology:
        gaps.append('缺少病理报告')
    if not demographics.get('name'):
        gaps.append('缺少患者基本信息')

    # ---- report_title ----
    primary_dx = demographics.get('primary_diagnosis', '')
    report_title = f'{primary_dx}患者病情概览' if primary_dx else '患者病情概览'

    ctx = {
        'demographics': demographics,
        'has_critical': has_critical,
        'critical_alerts': critical_alerts,
        'timeline': timeline,
        'pathology': pathology,
        'pathology_tag': None,
        'genetic_highlights': genetic_highlights,
        'ihc_note': None,
        'medication_summary': medication_summary,
        'medication_table': medication_table,
        'medication_prescription_date': medication_prescription_date,
        'medication': {
            'current': [m['label'] for m in medication_summary],
            'history': [m['label'] for m in medication_summary],
        },
        'imaging_summary': imaging_summary,
        'tumor_marker_tables': tumor_marker_tables,
        'lab_trend': lab_trend_rows,
        'lab_flat': lab_flat,
        'lab_abnormal': lab_abnormal,
        'categorized_lab': categorized_lab,
        'chart_svg_ca199': chart_svg_ca199,
        'chart_svg': chart_svg,
        'chart_svg_normalized': chart_svg_normalized,
        'chart_svg_absolute': chart_svg_absolute,
        'marker_sync_alert': marker_sync_alert,
        'key_concerns': key_concerns,
        'consultation_questions': consultation_questions,
        'files': files,
        'gaps': gaps,
        'updated_at': profile.get('generated_at', ''),
        'report_title': report_title,
        'lab_analysis_conclusion': lab_analysis_conclusion,
        'clinical_summary': clinical_summary,
        'pathology_diagnosis': pathology_diagnosis,
        'ihc_items': ihc_items,
        'pd_l1': pd_l1,
        'timeline_items': timeline_items,
        'pancreatic_consensus_link': 'https://mp.weixin.qq.com/s/Vpn2oH9cDgsOPg5oekvwCg',
        'pancreatic_consensus_text': '胰腺癌精准检测与分子诊断中国专家共识（2025版）',
    }
    return ctx


def _infer_modality(filename: str) -> str:
    """从文件名推断影像模态。"""
    lower = (filename or '').lower()
    if 'ct' in lower:
        return 'CT'
    if 'mri' in lower or '核磁' in lower:
        return 'MRI'
    if 'pet' in lower:
        return 'PET-CT'
    if '超声' in lower or 'b超' in lower or 'us' in lower:
        return '超声'
    if 'x线' in lower or 'dr' in lower:
        return 'X线'
    return '影像'


def _generate_marker_svg(marker_data: Dict[str, Any]) -> str:
    """用纯字符串模板生成 SVG 折线图。"""
    rows = marker_data.get('rows', [])
    if not rows:
        return ''
    # 数据点
    values = []
    dates = []
    for r in rows:
        try:
            v = float(r.get('value'))
            values.append(v)
            dates.append(r.get('date', ''))
        except (ValueError, TypeError):
            continue
    if not values:
        return ''

    width, height = 360, 160
    padding = 40
    max_val = max(values) if values else 1
    min_val = min(values)
    y_range = max(max_val - min_val, max_val * 0.2, 1)
    y_max = max_val + y_range * 0.2

    def to_x(i):
        if len(values) == 1:
            return width - padding
        return padding + (width - 2 * padding) * i / (len(values) - 1)

    def to_y(v):
        if y_max == 0:
            return height - padding
        return height - padding - (height - 2 * padding) * (v / y_max)

    points = [f'{to_x(i):.1f},{to_y(v):.1f}' for i, v in enumerate(values)]
    polyline = ' '.join(points)

    # 圆点
    dots = []
    for i, v in enumerate(values):
        cx, cy = to_x(i), to_y(v)
        is_abn = rows[i].get('is_abnormal') if i < len(rows) else False
        fill = '#e74c3c' if is_abn else '#1c5ca8'
        dots.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="3.5" fill="{fill}"/>')

    # 参考线
    ref_line = ''
    ref = marker_data.get('ref_range', '')

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'style="max-width:100%;height:auto;">'
        f'<rect width="{width}" height="{height}" fill="#fafbfc"/>'
        f'<polyline points="{polyline}" fill="none" stroke="#1c5ca8" stroke-width="2"/>'
        f'{"".join(dots)}'
    )
    # X 轴日期标签
    for i, d in enumerate(dates):
        label = d[5:] if len(d) >= 10 else d  # MM-DD
        svg += f'<text x="{to_x(i):.1f}" y="{height - 10}" font-size="9" fill="#6b7280" text-anchor="middle">{label}</text>'
    svg += '</svg>'
    return svg


def _condense_timeline_with_llm(
    timeline: List[Dict[str, Any]],
    profile: Dict[str, Any],
    groups: Dict[str, List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    """用 LLM 精简时间轴，提炼 12-18 个关键治疗节点。
    失败时返回去重后仍有序的原始时间轴。
    """
    try:
        from scripts.v2.llm_client import call_llm_with_retry
    except ImportError:
        return timeline

    # 构建纯文本输入
    lines = ['日期 | 类别 | 内容']
    for t in timeline:
        d = t['dates'][0] if t['dates'] else ''
        cat = t['category']
        note = t['note'][:200]
        lines.append(f'{d} | {cat} | {note}')
    text = '\n'.join(lines)

    schema = {
        'type': 'object',
        'properties': {
            'events': {
                'type': 'array',
                'items': {
                    'type': 'object',
                    'properties': {
                        'date': {'type': 'string'},
                        'title': {'type': 'string'},
                        'note': {'type': 'string'},
                    },
                },
            },
        },
    }
    prompt = (
        '你是肿瘤科病案整理专家。下面是一个胰腺癌患者的所有就诊记录时间轴，可能包含重复或琐碎条目。'
        '请提炼出 12-18 条关键治疗节点的时序摘要，按日期排序。每个节点包含：\n'
        '- 日期（原日期或年月）\n'
        '- 简要标题（如"AG方案开始化疗"、"Whipple术后1周"、"影像评估SD"、"CA199显著下降"）\n'
        '- 一句话临床意义\n'
        '合并同一天同一类别的重复条目。输出 JSON，events 数组。'
    )
    messages = [
        {'role': 'system', 'content': prompt},
        {'role': 'user', 'content': text},
    ]
    try:
        result = call_llm_with_retry(messages, schema, max_tokens=4000)
        events = result.get('events', [])
        if not events:
            return timeline
        return [
            {
                'dates': [e.get('date', '')],
                'title': e.get('title', ''),
                'category': 'key_concerns',
                'note': e.get('note', ''),
            }
            for e in events
        ]
    except Exception:
        return timeline


# ---------------------------------------------------------------------------
# 渲染入口
# ---------------------------------------------------------------------------
def render_html_report(
    profile: Dict[str, Any],
    groups: Dict[str, List[Dict[str, Any]]],
    output_dir: Path,
) -> Optional[Path]:
    """渲染 HTML 报告。返回输出路径，失败返回 None。"""
    output_path = Path(output_dir) / 'report.html'

    if not _JINJA2_AVAILABLE:
        logger.warning('Jinja2 未安装，跳过 HTML 渲染')
        return None

    if not _TEMPLATE_PATH.exists():
        logger.warning('模板文件不存在: %s', _TEMPLATE_PATH)
        return None

    ctx = compute_report_context(profile, groups)

    try:
        env = Environment(
            loader=FileSystemLoader(str(_TEMPLATE_PATH.parent)),
            autoescape=select_autoescape(['html', 'xml']),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        # 注册 raw filter 用于 chart_svg
        env.filters['raw'] = lambda x: x if isinstance(x, str) else ''
        template = env.get_template(_TEMPLATE_PATH.name)
        html = template.render(**ctx)
        output_path.write_text(html, encoding='utf-8')
        logger.info('HTML 报告已生成: %s', output_path)
        return output_path
    except Exception as exc:
        logger.exception('模板渲染失败: %s', exc)
        return None
