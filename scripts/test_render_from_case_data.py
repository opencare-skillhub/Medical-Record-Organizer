"""
测试脚本：用 case_report_data.json 测试 HTML 生成效果

将测试数据转换为 render_html_report 所需的 profile + groups 格式，
然后渲染 HTML 报告。
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

# 确保项目根在 sys.path 中
_ProjectRoot = Path(__file__).resolve().parent.parent
if str(_ProjectRoot) not in sys.path:
    sys.path.insert(0, str(_ProjectRoot))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


# 肿瘤标志物参考范围
_TUMOR_MARKER_REFS = {
    'CEA': {'ref_range': (0, 5.2), 'unit': 'ng/mL'},
    'CA199': {'ref_range': (0, 37), 'unit': 'U/mL'},
    'CA125': {'ref_range': (0, 35), 'unit': 'U/mL'},
    'CA724': {'ref_range': (0, 6.9), 'unit': 'U/mL'},
    'CA50': {'ref_range': (0, 25), 'unit': 'U/mL'},
    'CA242': {'ref_range': (0, 20), 'unit': 'U/mL'},
    'AFP': {'ref_range': (0, 7), 'unit': 'ng/mL'},
}

# 字段名映射（json key → 标准 key）
_TM_FIELD_MAP = {
    'CA-199': 'CA199',
    'CA-125': 'CA125',
    'CA-724': 'CA724',
    'CA-242': 'CA242',
    'CA-50': 'CA50',
}


def convert_case_data_to_profile_groups(
    case_data: Dict[str, Any],
) -> tuple[Dict[str, Any], Dict[str, List[Dict[str, Any]]]]:
    """将 case_report_data.json 转换为 render_html_report 所需的 profile + groups 格式。"""

    # ======== 1. demographics ========
    presc = case_data.get('presc', {}) or {}
    raw = presc.get('raw', {}) or {}
    demographics = {
        'name': raw.get('patient_name', '秦晓强'),
        'gender': '男',
        'age': str(raw.get('patient_name', '')) and '49',
        'primary_diagnosis': raw.get('diagnosis', '胰腺恶性肿瘤'),
        'icd_code': 'C25.900',
        'height': '175',
        'weight': '80',
    }

    # ======== 2. timeline ========
    timeline_events = case_data.get('timeline_events', []) or []
    # 从就诊记录补全更多时间线事件
    full_text = presc.get('summary', '') or ''
    extended_timeline = _build_timeline(timeline_events, full_text, presc)

    # ======== 3. imaging group ========
    imaging_group = _build_imaging_group(case_data.get('imaging_entries', []) or [])

    # ======== 4. pathology group ========
    pathology_group = _build_pathology_group(case_data.get('pathology_entries', []) or [])

    # ======== 5. medication ========
    medication_timeline = _build_medication(presc)

    # ======== 6. lab_trends (profile 层) ========
    lab_trends = _build_lab_trends(case_data.get('tm_records', []) or [])

    # ======== 7. lab_analysis (简单静态分析，不调用 LLM) ========
    lab_analysis = _build_lab_analysis(lab_trends)

    # ======== 8. imaging_narrative ========
    imaging_narrative = _build_imaging_narrative(imaging_group)

    # ======== 9. 组装 groups ========
    groups = {}
    if imaging_group:
        groups['imaging'] = imaging_group
    if pathology_group:
        groups['pathology'] = pathology_group

    # 添加 basic_info group 以便 render 正确提取人口统计信息
    groups['basic_info'] = [{
        '_source_file': 'basic_info',
        'document_date': '2025-03-31',
        'report_date': '2025-03-31',
        'report_type': 'basic_info',
        'demographics': demographics,
        'findings': [],
        'conclusion': '',
        'diagnoses': [{'name': demographics.get('primary_diagnosis', ''), 'icd10': demographics.get('icd_code', '')}],
        'test_items': [],
        'medications': [],
    }]

    # ======== 10. 组装 profile ========
    output_dir = Path(__file__).resolve().parent.parent / 'output'
    profile = {
        'patient_id': 'P_test_case',
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'input_dir': str(Path(__file__).resolve().parent.parent),
        'output_dir': str(output_dir),
        'file_count': 0,
        'map_count': 0,
        'groups': {k: len(v) for k, v in groups.items()},
        'lab_trends': lab_trends,
        'lab_analysis': lab_analysis,
        'medication_timeline': medication_timeline,
        'imaging_narrative': imaging_narrative,
    }

    return profile, groups


def _build_timeline(
    events: List[Dict[str, Any]],
    summary: str,
    presc: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """构建诊疗时间线。"""
    timeline = []

    # 从 presc.full_text 中提取更多事件
    full_text = presc.get('full_text', '') or ''

    # 关键事件列表（从就诊记录中人工提取）
    key_events = [
        ('2023-06-23', '就诊发现胰头占位', '彩超：肝内实性占位、腹水；CT：胰腺头部MT可能大', ''),
        ('2023-06-27', 'PET-CT检查', '胰头部MT伴远端胰管扩张，腹腔淋巴结转移，腹膜广泛转移伴腹盆腔积液', ''),
        ('2023-06-30', '腹腔镜探查+大网膜活检术', '网膜结节：大片粘液湖内见异型腺上皮，倾向粘液腺癌', ''),
        ('2023-07-06', '病理确诊：转移/浸润性粘液腺癌', '免疫组化：CK7(-)、CK19(+)、SMAD4(+)、CDX2(88)(+)、SATB2(-)、CK20(+)', 'key_concerns'),
        ('2023-07-11', '开始AG方案化疗 C1D1', '白蛋白紫杉醇+吉西他滨', 'medication'),
        ('2023-09-08', '疗效评估：PR（部分缓解）', '肿瘤标志物显著下降，病灶缩小', ''),
        ('2023-10-23', '疗效评估：SD（疾病稳定）', 'C4结束后评估', ''),
        ('2024-01-02', '疗效评估：SD + 增强CT复查', '胰头MT较前稍缩小，腹膜转移部分缩小，腹腔积液较前减少', ''),
        ('2024-09-05', '增强CT复查', '胰头低密度分叶状肿块伴高密度影较前稍缩小，约39*34mm', ''),
        ('2025-02-09', '最近一次随访评估', '持续SD，CA724持续下降趋势', ''),
        ('2025-03-31', '专病门诊就诊 · 继续化疗', '手脚麻木（化疗副作用），继续AG方案', 'medication'),
    ]

    for date, title, note, category in key_events:
        timeline.append({
            'dates': [date],
            'title': title,
            'category': category,
            'note': note,
        })

    timeline.sort(key=lambda x: x['dates'][0] if x['dates'] else '')
    return timeline


def _build_imaging_group(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """从影像条目构建 imaging group。"""
    group = []

    # 去重：只保留有实质内容的影像报告
    seen_texts = set()
    for entry in entries:
        text = (entry.get('text', '') or '').strip()
        if not text or len(text) < 50:
            continue

        # 跳过非影像文件（如好大夫在线文章、DICOM截图）
        if '好大夫在线' in text:
            continue
        if 'DICOM CT' in text and '影像尺寸' in text:
            continue

        # 去重（相似文本）
        text_hash = text[:100]
        if text_hash in seen_texts:
            continue
        seen_texts.add(text_hash)

        date = entry.get('date', '') or '日期待确认'
        file = entry.get('file', '')

        # 推断模态
        modality = 'CT'
        if 'PET' in text or 'FDG' in text:
            modality = 'PET-CT'
        elif '超声' in text or '彩超' in text:
            modality = '超声'

        # 提取关键发现
        findings = _extract_imaging_findings(text)

        group.append({
            '_source_file': file,
            'document_date': date if date != '未识别' else '日期待确认',
            'report_date': date if date != '未识别' else '日期待确认',
            'report_type': 'imaging',
            'modality': modality,
            'findings': findings,
            'conclusion': findings[-1] if findings else '',
            'lab_values': [],
            'test_items': [],
            'medications': [],
            'diagnoses': [],
        })

    return group


def _extract_imaging_findings(text: str) -> List[str]:
    """从影像文本中提取关键发现。"""
    findings = []

    # 提取诊断意见
    if '放射学诊断' in text:
        parts = text.split('放射学诊断')
        if len(parts) > 1:
            diag_text = parts[1].strip()
            # 按句号/分号分割
            for sentence in diag_text.replace('。', '\n').replace('；', '\n').split('\n'):
                s = sentence.strip()
                if s and len(s) > 3:
                    findings.append(s)
    elif '超声印象' in text:
        parts = text.split('超声印象')
        if len(parts) > 1:
            diag_text = parts[1].strip()
            for sentence in diag_text.replace('\n', '。').split('。'):
                s = sentence.strip()
                if s and len(s) > 3:
                    findings.append(s)

    if not findings:
        # 如果没有明确诊断，提取检查方法描述
        lines = [l.strip() for l in text.split('\n') if l.strip()]
        for line in lines:
            if '检查方法' in line or '对比' in line:
                findings.append(line)
                break

    return findings


def _build_pathology_group(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """从病理条目构建 pathology group。"""
    group = []

    for entry in entries:
        text = (entry.get('text', '') or '').strip()
        file = entry.get('file', '')

        # 跳过非病理条目
        if '好大夫在线' in text:
            continue
        if not text or len(text) < 30:
            continue

        # 只保留有病理关键字的条目
        if not any(kw in text for kw in ['病理', '粘液腺癌', '免疫组化', '基因检测', 'CK7', 'CK19', 'KRAS', 'ATM', 'SMAD4']):
            continue

        date = entry.get('date', '') or '日期待确认'
        if date == '未识别':
            # 尝试从文本提取日期
            if '2023/07/06' in text:
                date = '2023-07-06'
            elif '2023-07-03' in text:
                date = '2023-07-03'

        # 判断类型
        report_type = 'pathology'
        specimen_type = '病理'
        test_items = []

        # 提取免疫组化（两种格式：test_items 和 ihc_markers）
        ihc_items = _extract_ihc(text)
        test_items.extend(ihc_items)
        ihc_markers_list = []
        for item in ihc_items:
            ihc_markers_list.append({
                'marker': item.get('gene_name', ''),
                'result': item.get('detection_result', ''),
            })

        # 提取基因检测
        gene_items = _extract_genes(text)
        test_items.extend(gene_items)

        # 提取病理结论
        conclusion = ''
        if '转移/浸润性粘液腺癌' in text:
            conclusion = '转移/浸润性粘液腺癌，免疫组化提示表达肠型标记'

        findings = []
        if 'CK7（-），CK19（+），SMAD4（+），CDX2-88（+），SATB2（-），CK20（+）' in text:
            findings = ['CK7(-)', 'CK19(+)', 'SMAD4(+)', 'CDX2(+)', 'SATB2(-)', 'CK20(+)']
        elif 'CK7' in text and 'CK20' in text:
            findings.append('肠型分化表型')

        group.append({
            '_source_file': file,
            'document_date': date,
            'report_date': date,
            'report_type': report_type,
            'specimen_type': specimen_type,
            'findings': findings,
            'conclusion': conclusion,
            'test_items': test_items,
            'ihc_markers': ihc_markers_list,
            'lab_values': [],
            'medications': [],
            'diagnoses': [],
        })

    return group


def _extract_ihc(text: str) -> List[Dict[str, Any]]:
    """从文本中提取免疫组化结果。"""
    items = []
    ihc_markers = {
        'CK7': 'CK7',
        'CK19': 'CK19',
        'SMAD4': 'SMAD4',
        'CDX2': 'CDX2',
        'SATB2': 'SATB2',
        'CK20': 'CK20',
    }

    for marker, name in ihc_markers.items():
        # 匹配 CK7（-）或 CK7(-)
        import re
        pattern = rf'{marker}[^）)]*[（(]([+\-±])'
        m = re.search(pattern, text)
        if m:
            result = m.group(1)
            significance = ''
            if marker == 'CDX2' and result == '+':
                significance = '肠型分化'
            elif marker == 'SATB2' and result == '-':
                significance = '不支持结直肠癌转移'
            elif marker == 'SMAD4' and result == '+':
                significance = '保留功能'
            items.append({
                'gene_name': name,
                'detection_result': result,
                'result': result,
                'is_pathogenic': False,
                'category': 'ihc',
                'clinical_significance': significance,
            })

    return items


def _extract_genes(text: str) -> List[Dict[str, Any]]:
    """从文本中提取基因检测结果。"""
    items = []

    # ATM 致病基因
    if 'ATM' in text and ('致病' in text or '突变' in text):
        items.append({
            'gene_name': 'ATM',
            'detection_result': '致病，移码缺失（胚系）',
            'result': '致病，移码缺失（胚系）',
            'is_pathogenic': True,
            'category': 'gene',
            'clinical_significance': '胚系突变',
        })

    # KRAS 野生型
    if 'KRAS野生型' in text:
        items.append({
            'gene_name': 'KRAS',
            'detection_result': '野生型',
            'result': '野生型',
            'is_pathogenic': False,
            'category': 'gene',
            'clinical_significance': '',
        })

    # VEGFR 突变
    if 'VEGFR' in text and '突变' in text:
        items.append({
            'gene_name': 'VEGFR',
            'detection_result': '突变',
            'result': '突变',
            'is_pathogenic': False,
            'category': 'gene',
            'clinical_significance': '',
        })

    # GNAS 突变
    if 'GNAS' in text and '突变' in text:
        items.append({
            'gene_name': 'GNAS',
            'detection_result': '突变',
            'result': '突变',
            'is_pathogenic': False,
            'category': 'gene',
            'clinical_significance': '',
        })

    # UGT1A1 纯合（药物毒性）
    if 'UGT1A1' in text and '纯合' in text:
        items.append({
            'gene_name': 'UGT1A1',
            'detection_result': '纯合（*6/*28）',
            'result': '纯合（*6/*28）',
            'is_pathogenic': True,
            'category': 'drug_metabolism',
            'clinical_significance': '伊立替康副作用风险高',
        })

    return items


def _build_medication(presc: Dict[str, Any]) -> Dict[str, Any]:
    """构建用药时间线。"""
    raw = presc.get('raw', {}) or {}
    full_text = raw.get('full_text', '') or ''

    # 从处方中提取药物列表
    medications = [
        {
            'name': '注射用紫杉醇(白蛋白结合型)',
            'drug': '白蛋白紫杉醇',
            'dosage': '180mg/d1',
            'route': '静滴',
            'purpose': '化疗（AG方案）',
            'start_date': '2023-07-11',
            'type': '化疗',
        },
        {
            'name': '注射用盐酸吉西他滨',
            'drug': '吉西他滨',
            'dosage': '8支/d1',
            'route': '静滴',
            'purpose': '化疗（AG方案）',
            'start_date': '2023-07-11',
            'type': '化疗',
        },
        {
            'name': '地塞米松磷酸钠注射液',
            'drug': '地塞米松',
            'dosage': '5mg 1支/d1',
            'route': '静推',
            'purpose': '预处理',
            'start_date': '2023-07-11',
            'type': '辅助用药',
        },
        {
            'name': '盐酸帕洛诺司琼注射液',
            'drug': '帕洛诺司琼',
            'dosage': '0.25mg 1支/d1',
            'route': '静滴',
            'purpose': '止吐',
            'start_date': '2023-07-11',
            'type': '辅助用药',
        },
        {
            'name': '注射用谷胱甘肽',
            'drug': '谷胱甘肽',
            'dosage': '0.6g 3支/d1',
            'route': '静滴',
            'purpose': '保肝',
            'start_date': '2023-07-11',
            'type': '辅助用药',
        },
        {
            'name': '乳果糖口服溶液',
            'drug': '乳果糖',
            'dosage': '20ml bid',
            'route': '口服',
            'purpose': '通便（胃肠胀气）',
            'start_date': '2024-01-03',
            'type': '辅助用药',
        },
    ]

    # 从文本中统计累计次数
    import re
    c_pattern = r'C(\d+)D1'
    cycles = re.findall(c_pattern, full_text)
    max_cycle = max((int(c) for c in cycles), default=38)

    return {
        'regimens': [{'name': 'AG方案', 'description': '白蛋白紫杉醇+吉西他滨'}],
        'timeline': medications,
        'response_assessments': [
            {'date': '2023-09-08', 'response': 'PR', 'note': '部分缓解'},
            {'date': '2023-10-23', 'response': 'SD', 'note': '疾病稳定'},
            {'date': '2024-01-02', 'response': 'SD', 'note': '疾病稳定'},
            {'date': '2025-02-09', 'response': 'SD', 'note': '持续稳定'},
        ],
        'toxicities': [
            {'type': '手脚麻木', 'description': '化疗相关神经毒性', 'onset': '2024-01-03'},
            {'type': '胃肠胀气', 'description': '消化系统副作用', 'onset': '2024-01-03'},
        ],
        'total_cycles': max_cycle,
    }


def _build_lab_trends(tm_records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """构建检验指标趋势数据。"""
    trends: Dict[str, Any] = {}

    for record in tm_records:
        date = record.get('date', '') or record.get('日期', '')

        # 遍历所有标志物字段
        for raw_key, raw_value in record.items():
            if raw_key in ('date', '日期'):
                continue

            # 映射字段名
            std_key = _TM_FIELD_MAP.get(raw_key, raw_key)

            if std_key not in _TUMOR_MARKER_REFS:
                continue

            ref_info = _TUMOR_MARKER_REFS[std_key]

            if std_key not in trends:
                trends[std_key] = {
                    'unit': ref_info['unit'],
                    'ref_range': ref_info['ref_range'],
                    'trend': [],
                }

            # 处理异常值（如 ">300"）
            try:
                value = float(raw_value)
            except (ValueError, TypeError):
                if isinstance(raw_value, str) and raw_value.startswith('>'):
                    try:
                        value = float(raw_value[1:])
                    except (ValueError, TypeError):
                        value = None
                else:
                    value = None

            ref_low, ref_high = ref_info['ref_range']
            abnormal = value is not None and (value < ref_low or value > ref_high)

            trends[std_key]['trend'].append({
                'date': date,
                'value': value if value is not None else raw_value,
                'unit': ref_info['unit'],
                'abnormal': abnormal,
                'flag': '↑' if (value is not None and value > ref_high) else ('↓' if (value is not None and value < ref_low) else ''),
                'source': 'tm_records',
            })

    return trends


def _build_lab_analysis(lab_trends: Dict[str, Any]) -> Dict[str, Any]:
    """简单静态分析（不调用 LLM）。"""
    analysis = {}

    for indicator, data in lab_trends.items():
        trend_rows = data.get('trend', [])
        if not trend_rows:
            continue

        values = []
        for row in trend_rows:
            v = row.get('value')
            if v is not None:
                try:
                    values.append(float(v))
                except (ValueError, TypeError):
                    pass

        if not values:
            continue

        ref_low, ref_high = data.get('ref_range', (None, None))
        latest = values[-1]
        first = values[0]

        # 判断趋势
        if len(values) >= 3:
            recent_avg = sum(values[-3:]) / 3
            early_avg = sum(values[:3]) / 3
            if recent_avg < early_avg * 0.8:
                trend_summary = '持续下降'
            elif recent_avg > early_avg * 1.2:
                trend_summary = '持续上升'
            else:
                trend_summary = '波动/稳定'
        else:
            trend_summary = '数据不足'

        # 判断预警级别
        has_any_abnormal = any(row.get('abnormal') for row in trend_rows)
        if latest > ref_high * 2 if ref_high else False:
            alert_level = 'warning'
        elif has_any_abnormal:
            alert_level = 'warning'
        else:
            alert_level = 'normal'

        pct_change = ((latest - first) / abs(first) * 100) if first != 0 else 0

        analysis[indicator] = {
            'trend_summary': trend_summary,
            'alert_level': alert_level,
            'clinical_inference': f'{indicator} 从 {first} 变化到 {latest}（{pct_change:.1f}%）',
            'consecutive_rises': _count_consecutive_rises(values),
            'latest_value': latest,
            'ref_range': data.get('ref_range'),
        }

    return analysis


def _count_consecutive_rises(values: List[float]) -> int:
    """计算从末尾算起的连续上升次数。"""
    if len(values) < 2:
        return 0
    count = 0
    for i in range(len(values) - 1, 0, -1):
        if values[i] > values[i - 1]:
            count += 1
        else:
            break
    return count


def _build_imaging_narrative(imaging_group: List[Dict[str, Any]]) -> Dict[str, Any]:
    """构建影像叙事。"""
    primary_lesion_timeline = []
    metastasis_timeline = []

    for item in imaging_group:
        date = item.get('document_date', '') or '日期待确认'
        findings = item.get('findings', [])
        modality = item.get('modality', '')

        for f in (findings if isinstance(findings, list) else [findings]):
            f_str = str(f) if f else ''
            if '胰头' in f_str:
                primary_lesion_timeline.append({'date': date, 'finding': f_str, 'modality': modality})
            elif '腹膜' in f_str or '转移' in f_str or '积液' in f_str:
                metastasis_timeline.append({'date': date, 'finding': f_str, 'modality': modality})

    return {
        'primary_lesion_timeline': primary_lesion_timeline,
        'metastasis_timeline': metastasis_timeline,
        'overall_response': '持续SD，病灶缩小趋势',
    }


def main():
    """主函数：加载测试数据并生成 HTML 报告。"""
    # 加载测试数据
    test_data_path = Path('/Users/qinxiaoqiang/Downloads/test_data/case_report_data.json')
    if not test_data_path.exists():
        print(f"❌ 测试数据不存在: {test_data_path}")
        return 1

    case_data = json.loads(test_data_path.read_text(encoding='utf-8'))
    print(f"📂 加载测试数据: {test_data_path}")
    print(f"   时间线事件: {len(case_data.get('timeline_events', []))}")
    print(f"   影像条目: {len(case_data.get('imaging_entries', []))}")
    print(f"   病理条目: {len(case_data.get('pathology_entries', []))}")
    print(f"   肿瘤标志物记录: {len(case_data.get('tm_records', []))}")

    # 转换为 profile + groups 格式
    profile, groups = convert_case_data_to_profile_groups(case_data)

    print(f"\n📊 转换结果:")
    print(f"   profile keys: {list(profile.keys())}")
    print(f"   groups keys: {list(groups.keys())}")
    for k, v in groups.items():
        print(f"   {k}: {len(v)} 条")
    print(f"   lab_trends 指标数: {len(profile.get('lab_trends', {}))}")
    for indicator, data in profile.get('lab_trends', {}).items():
        print(f"     {indicator}: {len(data.get('trend', []))} 条记录")
    print(f"   medication_timeline: {len(profile.get('medication_timeline', {}).get('timeline', []))} 种药物")

    # 注入 MDT 结果，验证渲染层能优先使用多学科输出
    profile["mdt_analysis"] = {
        "concerns": [
            {
                "title": "肿瘤标志物趋势与影像变化需联合判断",
                "analysis": "CEA、CA199、CA724、CA50 等指标存在同步变化信号，需结合影像变化判断疾病活动度。",
                "priority": "high",
                "discipline": "oncology",
                "disciplines": ["oncology", "radiology"],
                "suggested_direction": "关注近期标志物趋势与影像复查是否一致。",
            },
            {
                "title": "长期化疗后的毒性与支持治疗",
                "analysis": "患者已接受较长疗程化疗，存在神经毒性与营养风险，需要持续支持治疗。",
                "priority": "medium",
                "discipline": "pharmacy",
                "disciplines": ["pharmacy", "nursing"],
                "suggested_direction": "继续关注神经毒性、营养状态与导管维护。",
            },
        ]
    }

    # 生成 HTML 报告
    output_dir = _ProjectRoot / 'output'
    from scripts.render_html import render_html_report

    html_path = render_html_report(profile, groups, output_dir)

    if html_path and html_path.exists():
        print(f"\n✅ HTML 报告已生成: {html_path}")
        print(f"   文件大小: {html_path.stat().st_size:,} 字节")

        # 复制到 pancreatic_cancer_case_report_real.html（用户满意版本）
        import shutil
        named_path = html_path.parent / 'pancreatic_cancer_case_report_real.html'
        shutil.copy2(html_path, named_path)
        print(f"📄 已另存为: {named_path}")

        # 验证多指标图表
        html_text = html_path.read_text(encoding='utf-8')
        polyline_count = html_text.count('<polyline')
        print(f"   图表折线数: {polyline_count}")
        assert polyline_count >= 6, f'预期至少 6 条折线（多指标图），实际 {polyline_count}'

        sync_alert = '同步性提示' in html_text
        print(f"   同步性告警: {'✅' if sync_alert else '❌'}")
        assert sync_alert, '未找到同步性告警'

        multi_marker_title = '相对首值变化，首值=100' in html_text
        print(f"   归一化图标题: {'✅' if multi_marker_title else '❌'}")
        assert multi_marker_title, '未找到归一化图标题'

        legend_markers = ['CEA', 'CA199', 'CA125', 'CA724', 'CA50', 'CA242']
        found_markers = [m for m in legend_markers if m in html_text]
        print(f"   图例指标: {found_markers}")
        assert len(found_markers) >= 4, f'预期至少 4 个指标在图例中，实际 {len(found_markers)}'

        # 自动打开
        import webbrowser
        webbrowser.open(f"file://{html_path}")
        print(f"🌐 已在浏览器中打开报告")
        return 0
    else:
        print(f"\n❌ HTML 报告生成失败")
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
