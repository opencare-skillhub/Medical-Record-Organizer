"""
v2 Map 层

对单份脱敏后的医疗文本做 LLM 结构化提取。
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from scripts.v2.llm_client import call_llm_with_retry

logger = logging.getLogger(__name__)


EXTRACT_SCHEMA: Dict[str, Any] = {
    'type': 'object',
    'properties': {
        'report_type': {
            'type': 'string',
            'enum': ['lab_results', 'imaging', 'pathology', 'medication', 'clinical_records', 'basic_info', 'invoice', 'noise'],
        },
        'document_date': {'type': 'string', 'description': 'YYYY-MM-DD'},
        'confidence': {'type': 'number'},
        'demographics': {
            'type': 'object',
            'properties': {
                'name': {'type': 'string'},
                'gender': {'type': 'string'},
                'age': {'type': 'number'},
                'medical_record_no': {'type': 'string'},
            },
        },
        'sample_info': {
            'type': 'object',
            'description': '基因检测/病理报告的样本与临床信息',
            'properties': {
                'specimen_type': {'type': 'string', 'description': '样本类型：石蜡切片/血液/胸水等'},
                'biopsy_site': {'type': 'string', 'description': '取样部位：胰腺/肺/肝等'},
                'tumor_type': {'type': 'string', 'description': '肿瘤类型：胰腺癌/肺腺癌等'},
                'cancer_stage': {'type': 'string', 'description': '肿瘤分期：III/IV/TNM等'},
                'sample_id': {'type': 'string', 'description': '样本编号/条码号'},
                'hospital': {'type': 'string', 'description': '送检机构'},
                'issuing_org': {'type': 'string', 'description': '出具方/检测机构，如华大基因、金域医学等'},
                'sampling_date': {'type': 'string', 'description': '取样/送检日期'},
                'receipt_date': {'type': 'string', 'description': '实验室收样日期'},
                'report_version': {'type': 'string', 'description': '报告版本号'},
                'reporting_platform': {'type': 'string', 'description': '检测平台/测序仪，如MGISEQ-2000/DNBSEQ-T7'},
                'gene_panel_size': {'type': 'string', 'description': '检测基因数，如689个实体瘤基因+69个胚系基因'},
            },
        },
        'lab_values': {
            'type': 'array',
            'description': '展平格式的检验指标（Shuffle 直接消费）',
            'items': {
                'type': 'object',
                'properties': {
                    'name': {'type': 'string'},
                    'value': {'type': 'number'},
                    'unit': {'type': 'string'},
                    'date': {'type': 'string', 'description': '该指标的检测日期，YYYY-MM-DD。从表格列头或上下文中提取，不要留空！'},
                    'ref_low': {'type': 'number'},
                    'ref_high': {'type': 'number'},
                    'abnormal': {'type': 'boolean'},
                    'fluctuation': {'type': 'string', 'description': '波动情况描述，如"较前上升"、"较前下降"、"持续稳定"、"波动"等'},
                    'note': {'type': 'string', 'description': '备注信息'},
                },
            },
        },
        'lab_analysis_conclusion': {
            'type': 'string',
            'description': '检验报告的分析结论/总结意见（如"肿瘤标志物整体呈下降趋势，提示治疗有效"）',
        },
        'lab_tests': {
            'type': 'object',
            'description': '嵌套结构（供下游按需使用）',
            'properties': {
                'tumor_markers': {'type': 'array'},
                'blood_routine': {'type': 'array'},
                'liver_kidney': {'type': 'array'},
            },
        },
        'imaging': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'modality': {'type': 'string'},
                    'date': {'type': 'string'},
                    'findings': {'type': 'string'},
                    'conclusion': {'type': 'string'},
                },
            },
        },
        'medications': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'name': {'type': 'string'},
                    'type': {'type': 'string'},
                    'start_date': {'type': 'string'},
                    'dosage': {'type': 'string'},
                    'dose': {'type': 'string'},
                    'route': {'type': 'string'},
                    'frequency': {'type': 'string'},
                    'purpose': {'type': 'string'},
                },
            },
        },
        'diagnoses': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'name': {'type': 'string'},
                    'stage': {'type': 'string'},
                    'icd10': {'type': 'string'},
                    'subtype': {'type': 'string'},
                    'confirmed_date': {'type': 'string'},
                },
            },
        },
        'timeline_items': {
            'type': 'array',
            'description': '就诊/诊疗时间轴条目（clinical_records 类型专用）',
            'items': {
                'type': 'object',
                'properties': {
                    'date': {'type': 'string', 'description': 'YYYY-MM-DD'},
                    'event': {'type': 'string', 'description': '事件描述，如"因皮肤变黄就诊"、"PTCD穿刺降黄手术"、"胰腺十二指肠切除术"等'},
                    'hospital': {'type': 'string', 'description': '医院名称'},
                    'result': {'type': 'string', 'description': '结果或备注'},
                    'severity': {'type': 'string', 'description': '严重程度标记，如"严重不良反应"等'},
                },
            },
        },
        'clinical_summary': {
            'type': 'string',
            'description': '临床摘要/病情概述（对 clinical_records/basic_info 类型）：用 2-3 句话总结患者的确诊时间、病种、分期、当前治疗阶段、关键问题和疗效评估',
        },
        'findings': {'type': 'array', 'items': {'type': 'string'}},
        'conclusion': {'type': 'string'},
        'procedures': {'type': 'array', 'items': {'type': 'string'}},
        'test_items': {
            'type': 'array',
            'description': '基因检测项目（pathology 类型）：体细胞突变/胚系突变列表',
            'items': {
                'type': 'object',
                'properties': {
                    'gene_name': {'type': 'string'},
                    'detection_result': {'type': 'string', 'description': '突变描述如G12D、R248W'},
                    'category': {'type': 'string', 'description': '体细胞/胚系'},
                    'is_pathogenic': {'type': 'boolean', 'description': '已知致病突变=true'},
                    'clinical_significance': {'type': 'string'},
                    'abundance': {'type': 'string', 'description': '突变丰度/频率%'},
                    'protein_change': {'type': 'string', 'description': '蛋白质改变如p.Gly12Asp'},
                    'chromosome': {'type': 'string', 'description': '染色体位置如chr12:25398284'},
                    'evidence_tier': {'type': 'string', 'description': '证据等级: 1A/1B/2A/2B/3'},
                },
            },
        },
        'pharmacogenomics': {
            'type': 'array',
            'description': '化疗药物代谢基因SNP检测结果：如UGT1A1*6/*28、DPYD等，对化疗方案选择关键',
            'items': {
                'type': 'object',
                'properties': {
                    'gene': {'type': 'string'},
                    'variant': {'type': 'string'},
                    'genotype': {'type': 'string'},
                    'drug': {'type': 'string'},
                    'risk': {'type': 'string', 'description': '毒副作用风险描述'},
                    'recommendation': {'type': 'string'},
                    'evidence_tier': {'type': 'string', 'description': '证据等级: 1A/1B/2A/2B'},
                },
            },
        },
        'qc_metrics': {
            'type': 'object',
            'description': '样本与测序质控信息（DNA提取、测序深度、覆盖度、Q30）',
            'properties': {
                'dna_quantity': {'type': 'string'},
                'insert_size': {'type': 'string', 'description': '插入片段长度'},
                'average_depth': {'type': 'string'},
                'coverage_100x': {'type': 'string', 'description': '目标区域覆盖度(100X)'},
                'q30_read1': {'type': 'string'},
                'q30_read2': {'type': 'string'},
                'quality': {'type': 'string'},
            },
        },
        'hrr_genes': {
            'type': 'array',
            'description': 'PARP抑制剂相关HRR基因检测结果（如BRCA1/2、ATM等，胰腺癌PARP用药关键）',
            'items': {
                'type': 'object',
                'properties': {
                    'gene': {'type': 'string'},
                    'status': {'type': 'string', 'description': '突变/野生型'},
                    'is_pathogenic': {'type': 'boolean'},
                },
            },
        },
        'drug_recommendations': {
            'type': 'array',
            'description': '临床用药解析：突变对应敏感/耐药药物列表',
            'items': {
                'type': 'object',
                'properties': {
                    'gene': {'type': 'string'},
                    'drug': {'type': 'string'},
                    'sensitivity': {'type': 'string', 'description': '敏感/可能敏感/耐药/可能耐药'},
                    'evidence': {'type': 'string', 'description': '证据来源如NCCN/FDA/NMPA'},
                    'indication': {'type': 'string', 'description': '适用肿瘤类型'},
                },
            },
        },
        'tmb_value': {'type': 'string', 'description': '肿瘤突变负荷值如 1.89 mut/Mb 或 TMB-Low'},
        'msi_status': {'type': 'string', 'description': '微卫星不稳定性状态: MSI-H / MSS / MSI-L'},
        'report_summary': {
            'type': 'string',
            'description': '报告结论摘要：关键突变总结、TMB值、MSI状态、用药提示',
        },
        'noise': {'type': 'array', 'items': {'type': 'string'}},
        'ihc_markers': {
            'type': 'array',
            'description': '免疫组化结果（pathology 类型专用）',
            'items': {
                'type': 'object',
                'properties': {
                    'marker': {'type': 'string', 'description': '标记物名称，如 CD163、CD20、PD-1 等'},
                    'result': {'type': 'string', 'description': '检测结果，如"组织细胞+"、"约10%免疫细胞+"、"(-)" 等'},
                    'clinical_meaning': {'type': 'string', 'description': '临床意义'},
                },
            },
        },
        'pathology_diagnosis': {
            'type': 'object',
            'description': '手术病理诊断要点（pathology 类型专用）',
            'properties': {
                'tumor_site': {'type': 'string', 'description': '肿瘤部位，如"胰头"'},
                'tumor_count': {'type': 'string', 'description': '肿瘤数目，如"单个"'},
                'tumor_size': {'type': 'string', 'description': '肿瘤大小，如"3.5×3.3×2.8cm"'},
                'tnm_stage': {'type': 'string', 'description': 'TNM 分期，如"T2N1M0"'},
                'pathology_diagnosis': {'type': 'string', 'description': '病理诊断，如"胰腺中分化导管腺癌"'},
                'resection_margin': {'type': 'string', 'description': '肿瘤切面，如"灰白灰黄、实性、质中"'},
                'risk_factors': {'type': 'array', 'items': {'type': 'string'}, 'description': '高危因素，如"胆总管壁浸润"、"脉管癌栓"等'},
            },
        },
        'pd_l1': {
            'type': 'object',
            'description': 'PD-L1 检测结果（pathology 类型专用）',
            'properties': {
                'cps': {'type': 'string', 'description': 'CPS 评分，如"CPS约20%"'},
                'tps': {'type': 'string', 'description': 'TPS 评分'},
            },
        },
    },
    'required': ['report_type', 'confidence'],
}

SYSTEM_PROMPT = """你是一名资深病案整理员。下面是一份医疗文件（已脱敏）。
请提取其中的结构化信息。

【通用规则】
1. report_type 必须准确，只能从以下枚举值中选择：
   - lab_results：检验报告（血常规/生化/肿瘤标志物/凝血等）
   - imaging：影像检查（CT/MRI/超声/内镜/PET-CT等）
   - pathology：病理报告（组织学/**基因检测**/免疫组化等） ← 基因检测归此类
   - medication：用药/处方/医嘱
   - clinical_records：出院小结/门诊/手术记录
   - basic_info：患者基本信息
   - invoice：发票/收据
   - noise：非医疗内容
2. document_date：报告日期，格式 YYYY-MM-DD。必须提取！如果文件中有明确日期（如
   "2024-12-31"、"2024年3月15日"），请准确提取；不确定则返回空字符串。
3. lab_values（检验指标）：所有检验指标用展平数组输出，**逐项提取表格数据**：
   - name/value/unit 必填，有参考范围时填 ref_low/ref_high/abnormal
   - **date 必填**：从表格列头/表头日期中提取每个指标对应的检测日期，格式 YYYY-MM-DD
   - fluctuation：波动情况描述（如"较前上升"、"较前下降"、"持续稳定"）
   - 如果原文有分析结论/总结意见，填入 lab_analysis_conclusion
4. medications 数组中每项用 name 字段（不是 drug）。
5. 如某字段在文件中不存在，返回空数组，不要编造。
6. confidence 反映你对该分类的把握（0-1）。

【基因检测报告（pathology 类型）专项指引】
当识别到文件是肿瘤基因检测报告时，按以下优先级提取：

	A. 检测结论页（优先）：
	   - 找到"体细胞变异检测结果"或"检测结果"汇总表
	   - 提取所有突变到 test_items 数组，每项含：
	     * gene_name（基因名如 KRAS）
	     * detection_result（突变描述如 G12D 突变）
	     * category（体细胞/胚系）
	     * is_pathogenic（已知致病突变=true）
	     * abundance（突变丰度/频率%，如 35.2%）
	     * protein_change（蛋白质改变，如 p.Gly12Asp）
	     * chromosome（染色体位置，如 chr12:25398284）
	     * clinical_significance（临床意义）
	     * evidence_tier（证据等级: 1A/1B/2A/2B/3）
	   - **已知致病突变（KRAS/TP53/ATM等）必须标注 is_pathogenic=true**

	B. 化疗药物代谢基因（pharmacogenomics，关键）：
	   - 找到"化疗药物相关SNP"或类似章节
	   - 提取 UGT1A1*6/*28、DPYD、ERCC1 等药物的基因型、对应药物、毒性风险
	   - 每项含 gene、variant、genotype、drug、risk、recommendation、evidence_tier

	C. 样本质控（qc_metrics）：
	   - DNA抽提量(ng): 合格/不合格
	   - 插入片段长度(bp): 如 128bp
	   - 目标区域平均测序深度(X): 如 3203.65X
	   - 目标区域覆盖度(100X): 如 99.46%
	   - 碱基测序质量Q30比例: Read1 96.76%, Read2 94.45%

	D. 免疫标志物：
	   - tmb_value: 如 "1.89 mut/Mb" 或 "TMB-Low" 或 "TMB<0.1"
	   - msi_status: 如 "MSI-H" 或 "MSS"
	   - 另外写到 report_summary 中

	E. HRR 基因（hrr_genes，PARP抑制剂相关）：
	   - 找到"PARP 抑制剂相关HRR 基因检测结果"章节
	   - 提取 BRCA1/2、ATM、PALB2 等 HRR 基因状态到 hrr_genes 数组

	F. 用药推荐（drug_recommendations）：
	   - 找到"可能敏感/可能耐药相关药物解析"章节
	   - 提取基因→药物关联，含 sensitivity(敏感/耐药)、evidence(FDA/NCCN)

H. 样本与临床信息（sample_info）：
   - 找到报告基本信息页
   - 提取以下字段：
     * specimen_type（样本类型：石蜡切片/血液等）
     * biopsy_site（取样部位：胰腺/肺/肝等）
     * tumor_type（肿瘤类型：胰腺癌等）
     * cancer_stage（肿瘤分期：III/IV等）
     * sample_id（样本编号）
     * hospital（送检机构）
     * issuing_org（出具方/检测机构：华大基因、金域医学等）
     * sampling_date（取样日期）和 receipt_date（收样日期）
     * report_version（报告版本/受控编号）
     * reporting_platform（检测平台：MGISEQ-2000等）
     * gene_panel_size（检测范围：如689个实体瘤基因+69个胚系基因）

I. 跳过：
   - 跳过基因定义、附录页（大量基因列表不是结果）
   - 跳过产品简介、免责声明等非结果内容

【临床记录（clinical_records 类型）专项指引】
当识别到文件是就诊经历、病史摘要或临床记录时：
   - 提取所有时间轴事件到 timeline_items，每项含 date/event/hospital/result/severity
   - 用 clinical_summary 写 2-3 句话病情概述：确诊时间+病种+分期+当前治疗+关键问题+疗效
   - 提取主要诊断到 diagnoses

【病理报告（pathology 类型）专项指引】
当识别到文件包含手术病理结果时：
   - 提取病理诊断要点到 pathology_diagnosis（肿瘤部位/数目/大小/TNM分期/病理诊断/切面/高危因素）
   - 提取免疫组化到 ihc_markers（marker/result/clinical_meaning）
   - 提取 PD-L1 到 pd_l1
   - 如果有基因检测结果，同时按上方"基因检测报告"专项指引提取
"""

# ---------------------------------------------------------------------------
# Map 后规则兜底：当 LLM 返回 noise / 低置信度时，用关键词纠正
# （解决真实测试中 bloodreport→noise、therapy_line→noise 等问题）
# ---------------------------------------------------------------------------
_KEYWORD_TYPE_RULES: List[tuple[str, str]] = [
    # 长关键词优先（避免短词如"CT"被基因文本中的 CTNNB1 误匹配）
    ('pathology', '病理诊断'),
    ('pathology', '免疫组化'),
    ('pathology', '肿瘤基因检测'),
    ('pathology', '基因检测'),
    ('pathology', '体细胞变异'),
    ('pathology', '胚系变异'),
    ('pathology', 'UGT1A1'),
    ('pathology', 'DPYD'),
    ('pathology', '化疗药物相关SNP'),
    ('pathology', '用药提示'),
    ('pathology', '组织学'),
    ('pathology', '活检'),
    ('pathology', 'MSI'),
    ('pathology', 'PD-L1'),
    ('pathology', 'KRAS'),
    ('pathology', 'TP53'),
    ('pathology', '突变'),
    ('lab_results', '肿瘤标志物'),
    ('lab_results', '糖类抗原'),
    ('lab_results', 'CA199'),
    ('lab_results', 'CA125'),
    ('lab_results', 'CA724'),
    ('lab_results', 'CA242'),
    ('lab_results', 'CEA'),
    ('lab_results', 'AFP'),
    ('lab_results', '参考区间'),
    ('lab_results', '测定值'),
    ('lab_results', '检验报告'),
    ('lab_results', '检验报告单'),
    ('lab_results', '指标变化趋势'),
    ('lab_results', '参考值范围'),
    ('lab_results', '正常上限'),
    ('lab_results', '血常规'),
    ('lab_results', '生化'),
    ('lab_results', '凝血功能'),
    ('lab_results', '癌胚抗原'),
    ('imaging', '影像所见'),
    ('imaging', '诊断意见'),
    ('imaging', '增强扫描'),
    ('imaging', '核磁共振'),
    ('imaging', 'PET-CT'),
    ('imaging', '平扫'),
    ('imaging', 'MRI'),
    ('imaging', 'CT'),
    ('imaging', '超声'),
    ('medication', '化疗方案'),
    ('medication', '化疗'),
    ('medication', '方案'),
    ('medication', '静滴'),
    ('medication', '服药'),
    ('medication', '处方'),
    ('medication', '医嘱'),
    ('clinical_records', '出院小结'),
    ('clinical_records', '门诊记录'),
    ('clinical_records', '主诉'),
    ('clinical_records', '现病史'),
    ('clinical_records', '体格检查'),
    ('clinical_records', '住院记录'),
    ('clinical_records', '入院日期'),
    ('basic_info', '患者姓名'),
    ('basic_info', '性别'),
    ('basic_info', '年龄'),
]


def _apply_keyword_fallback(
    text: str,
    filename: str,
    result: Dict[str, Any],
) -> Dict[str, Any]:
    """当 LLM 返回 noise 或置信度低时，用关键词规则兜底修正 report_type。

    不影响已有 lab_values/medications 等字段（仅修正 type）。

    修复：当多组关键词命中且最强匹配与 LLM 不同 → 覆盖误分类，避免
    target1/CA199 被标为 medication 等问题。
    """
    rt = (result.get('report_type') or 'noise').strip()
    conf = result.get('confidence', 0.0) or 0.0

    # 按关键词长度降序排列（越具体越优先，避免短词误匹配）
    sorted_rules = sorted(_KEYWORD_TYPE_RULES, key=lambda r: -len(r[1]))

    lower_text = text.lower()
    lower_name = filename.lower()

    # 扫描所有关键词匹配（不提前 return），收集最高得分的 type
    best_type = rt
    best_kw_len = 0
    for report_type, keyword in sorted_rules:
        if keyword.lower() in lower_text or keyword.lower() in lower_name:
            if len(keyword) > best_kw_len:
                best_kw_len = len(keyword)
                best_type = report_type
        # 不 break，继续扫描，确保最长的关键词胜出

    # 关键词得分显著更高时（匹配词更长），覆盖 LLM 结果
    if best_kw_len > 6 and best_type != rt:
        logger.info(
            'Map 关键词兜底: %s → %s (LLM 原类型=%s conf=%.2f)',
            filename, best_type, rt, conf,
        )
        result['report_type'] = best_type
        result['confidence'] = max(conf, 0.7)

    return result


# ---------------------------------------------------------------------------
# 类型专属二次提取：当 type 已确定但结构化字段全空时，用聚焦 Prompt 再调 LLM
# ---------------------------------------------------------------------------
_TYPE_EXTRACT_PROMPTS = {
    'lab_results': {
        'schema': {
            'type': 'object',
            'properties': {
                'lab_values': {
                    'type': 'array',
                    'items': {
                        'type': 'object',
                        'properties': {
                            'name': {'type': 'string'}, 'value': {'type': 'number'},
                            'unit': {'type': 'string'}, 'date': {'type': 'string'},
                            'ref_low': {'type': 'number'}, 'ref_high': {'type': 'number'},
                            'abnormal': {'type': 'boolean'}, 'fluctuation': {'type': 'string'},
                        },
                    },
                },
                'lab_analysis_conclusion': {'type': 'string'},
            },
        },
        'prompt': '你是检验报告数据提取器。从文本中提取所有检验指标，输出 JSON。lab_values 每项含 name/value/unit/date/ref_low/ref_high/abnormal/fluctuation。**必须逐行提取日期**，有分析结论时填入 lab_analysis_conclusion。',
    },
    'pathology': {
        'schema': {
            'type': 'object',
            'properties': {
                'test_items': {
                    'type': 'array',
                    'items': {
                        'type': 'object',
                        'properties': {
                            'gene_name': {'type': 'string'}, 'detection_result': {'type': 'string'},
                            'category': {'type': 'string'}, 'is_pathogenic': {'type': 'boolean'},
                            'evidence_tier': {'type': 'string'}, 'abundance': {'type': 'string'},
                        },
                    },
                },
                'pharmacogenomics': {
                    'type': 'array',
                    'items': {
                        'type': 'object',
                        'properties': {
                            'gene': {'type': 'string'}, 'variant': {'type': 'string'},
                            'genotype': {'type': 'string'}, 'drug': {'type': 'string'},
                            'risk': {'type': 'string'},
                        },
                    },
                },
                'ihc_markers': {
                    'type': 'array',
                    'items': {
                        'type': 'object',
                        'properties': {
                            'marker': {'type': 'string'}, 'result': {'type': 'string'},
                        },
                    },
                },
                'pathology_diagnosis': {'type': 'object'},
            },
        },
        'prompt': '你是基因检测和病理报告提取器。提取所有基因突变(test_items)、化疗药物代谢基因(pharmacogenomics)、免疫组化(ihc_markers)、病理诊断要点(pathology_diagnosis)。致病突变KRAS/TP53/ATM标is_pathogenic=true。输出 JSON。',
    },
    'imaging': {
        'schema': {
            'type': 'object',
            'properties': {
                'findings': {'type': 'array', 'items': {'type': 'string'}},
                'conclusion': {'type': 'string'},
            },
        },
        'prompt': '你是影像报告提取器。提取影像所见(findings)和诊断意见(conclusion)。输出 JSON。',
    },
    'medication': {
        'schema': {
            'type': 'object',
            'properties': {
                'medications': {
                    'type': 'array',
                    'items': {
                        'type': 'object',
                        'properties': {
                            'name': {'type': 'string'}, 'dosage': {'type': 'string'},
                            'route': {'type': 'string'}, 'frequency': {'type': 'string'},
                            'purpose': {'type': 'string'},
                        },
                    },
                },
            },
        },
        'prompt': '你是用药方案提取器。提取所有药物及其剂量、给药方式、频率。输出 JSON，medications 数组每项含 name/dosage/route/frequency。',
    },
}


def _typed_reextract(
    sanitized_text: str,
    filename: str,
    report_type: str,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """对已确定类型但字段为空的文件，用类型专属 Prompt 重新提取。"""
    cfg = _TYPE_EXTRACT_PROMPTS.get(report_type)
    if not cfg:
        return {}
    # 百万上下文模型，全量发送
    truncated = sanitized_text
    messages = [
        {'role': 'system', 'content': cfg['prompt']},
        {'role': 'user', 'content': f'文件名：{filename}\n\n{truncated}'},
    ]
    try:
        # 二阶段提取同样给足 256K token，避免截断
        result = call_llm_with_retry(messages, cfg['schema'], model=model, max_tokens=256000)
        logger.info('二次 LLM 提取成功 type=%s: %s', report_type, filename)
        return result
    except Exception as exc:
        logger.warning('二次 LLM 提取失败 %s: %s', filename, exc)
        return {}


def _is_structurally_empty(result: Dict[str, Any], report_type: str) -> bool:
    """判断某类型的关键结构化字段是否全为空。"""
    checks = {
        'lab_results': ['lab_values', 'lab_analysis_conclusion'],
        'pathology': ['test_items', 'pharmacogenomics', 'ihc_markers', 'pathology_diagnosis'],
        'imaging': ['findings', 'conclusion'],
        'medication': ['medications'],
        'clinical_records': ['diagnoses', 'timeline_items', 'clinical_summary'],
    }
    keys = checks.get(report_type, [])
    return all(not result.get(k) for k in keys)


def extract_single(
    sanitized_text: str,
    filename: str,
    *,
    model: Optional[str] = None,
    max_chars: int = 0,  # 0 = 不截断，模型支持百万上下文
) -> Dict[str, Any]:
    """单文件 LLM 提取。"""
    # 百万上下文模型不需要截断，全量发送
    truncated_text = sanitized_text

    messages = [
        {'role': 'system', 'content': SYSTEM_PROMPT},
        {'role': 'user', 'content': f'文件名：{filename}\n\n内容：\n{truncated_text}'},
    ]
    # 模型支持百万上下文，输出端应给足空间（256K token）确保基因报告42+条突变完整
    result = call_llm_with_retry(messages, EXTRACT_SCHEMA, model=model, max_tokens=256000)
    result.setdefault('report_type', 'noise')
    result.setdefault('confidence', 0.0)
    result['_source_file'] = filename
    # 向后兼容：document_date 也映射到 report_date
    if result.get('document_date') and not result.get('report_date'):
        result['report_date'] = result['document_date']
    # LLM 返回 noise 时用关键词规则兜底
    result = _apply_keyword_fallback(sanitized_text, filename, result)
    # 类型已确定但结构化字段全空 → 用类型专属 Prompt 二次提取
    rt = result.get('report_type', 'noise')
    if rt != 'noise' and _is_structurally_empty(result, rt):
        re_data = _typed_reextract(sanitized_text, filename, rt, model=model)
        if re_data:
            for k, v in re_data.items():
                if v and not result.get(k):
                    result[k] = v
    return result


def extract_batch(
    sanitized_dir: str,
    output_dir: str,
    *,
    model: Optional[str] = None,
    max_workers: int = 2,
) -> List[Dict[str, Any]]:
    """批量提取目录下所有脱敏文件。"""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    Path(output_dir).mkdir(parents=True, exist_ok=True)
    md_files = sorted(Path(sanitized_dir).glob('*.md'))

    def process_one(md_file: Path) -> Dict[str, Any]:
        out_path = Path(output_dir) / f'{md_file.stem}.json'
        if out_path.exists():
            try:
                cached = json.loads(out_path.read_text(encoding='utf-8'))
                # 缓存结果也过关键词兜底（防止早期跑的错误分类被永久缓存）
                return _apply_keyword_fallback(md_file.read_text(encoding='utf-8'), md_file.name, cached)
            except Exception:
                pass
        text = md_file.read_text(encoding='utf-8')
        try:
            result = extract_single(text, md_file.name, model=model)
        except Exception as exc:
            logger.exception('Map 提取失败: %s', md_file)
            result = {
                'report_type': 'error',
                'confidence': 0.0,
                '_source_file': md_file.name,
                'error': str(exc),
            }
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        return result

    results: List[Dict[str, Any]] = []
    if not md_files:
        return results

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(process_one, f) for f in md_files]
        for future in as_completed(futures):
            results.append(future.result())

    return results
