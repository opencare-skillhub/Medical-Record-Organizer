# PatientProfile Schema v1.0

> 本文档定义病情档案的完整 JSON 结构。
> 该结构比最终报告包含更多字段（中间态更完整），
> 患者版/医护版报告均为该结构的"视图投影"。

---

## 顶层结构

```json
{
  "schema_version": "1.0",
  "patient_id": "P_report_mess",
  "demographics": { ... },
  "chief_complaint": { ... },
  "diagnoses": [ ... ],
  "genetic_profile": { ... },
  "lab_tests": { ... },
  "imaging": { ... },
  "pathology": { ... },
  "medications": [ ... ],
  "surgeries": [ ... ],
  "treatment_history": [ ... ],
  "follow_up": [ ... ],
  "supportive_care": { ... },
  "alerts": [ ... ],
  "recommendations": { ... },
  "data_sources": { ... }
}
```

---

## 1. demographics（基本信息）

```json
{
  "name": "秦晓强",
  "gender": "男",
  "age": 49,
  "height_cm": null,
  "weight_kg": null,
  "bmi": null,
  "phone": null,
  "medical_record_no": null,
  "hospital": "本院",
  "race": null,
  "occupation": null,
  "marital_status": null
}
```

---

## 2. chief_complaint（主诉）

```json
{
  "onset_date": "2023-06-23",
  "symptoms": ["进食后腹胀不适"],
  "duration_days": 9,
  "progression": "无明显诱因出现进食后腹胀不适，不伴纳差、腹痛、恶心、呕吐、腹泻、便秘",
  "seeking_care_reason": "症状持续未缓解，遂就诊"
}
```

---

## 3. diagnoses（诊断实体）

每个诊断实体包含完整的元数据，支持多诊断并存。

```json
{
  "diagnoses": [
    {
      "id": "dx_001",
      "name": "胰腺恶性肿瘤",
      "subtype": "粘液腺癌",
      "icd10": "C25.9",
      "laterality": null,
      "grade": "中分化",
      "stage": {
        "tnm": {
          "t": "T2",
          "n": "N0",
          "m": "M0"
        },
        "ajcc": "IB期",
        "notes": "伴腹膜及淋巴结转移"
      },
      "confirmed_date": "2023-06-30",
      "confirmed_by": "腹腔镜探查+大网膜活检术",
      "hospital": "本院",
      "status": "active",
      "source_files": ["01 病情概述.pdf"]
    }
  ]
}
```

---

## 4. genetic_profile（基因/分子检测）

```json
{
  "tests": [
    {
      "id": "gene_001",
      "date": "2023-07-06",
      "facility": "本院",
      "method": "NGS",
      "specimen": "组织活检",
      "genes": [
        {"gene": "KRAS", "mutation": "野生型", "variant": null, "vaf": null},
        {"gene": "ATM", "mutation": "突变", "variant": null, "vaf": null},
        {"gene": "VEGFR", "mutation": "突变", "variant": null, "vaf": null}
      ],
      "tmb": null,
      "tmb_unit": "mut/Mb",
      "msi": "MSS",
      "pdl1_tps": null,
      "pdl1_cps": null,
      "source_files": ["2025-03-31_处方用药.JPG"]
    }
  ]
}
```

---

## 5. lab_tests（检验指标体系）

### 5.1 顶层结构

```json
{
  "summary": {
    "total_reports": 77,
    "date_range": {"start": "2023-06-01", "end": "2025-12-23"}
  },
  "categories": {
    "tumor_markers": { ... },
    "blood_routine": { ... },
    "liver_kidney": { ... },
    "coagulation": { ... },
    "thyroid": { ... },
    "other": { ... }
  }
}
```

### 5.2 tumor_markers（肿瘤标志物）

```json
{
  "tumor_markers": {
    "CEA": {
      "name": "癌胚抗原",
      "unit": "ng/ml",
      "ref_range": {"low": 0, "high": 5},
      "trend": [
        {"date": "2023-06-01", "value": 14.65, "flag": "↑", "source": "ca199.xlsx"},
        {"date": "2024-12-02", "value": 5.43, "flag": "↓", "source": "ca199.xlsx"},
        {"date": "2025-10-28", "value": 7.93, "flag": "↑", "source": "ca199.xlsx"}
      ]
    },
    "CA199": {
      "name": "糖类抗原 199",
      "unit": "U/ml",
      "ref_range": {"low": 0, "high": 37},
      "trend": [
        {"date": "2023-06-01", "value": 342, "flag": "↑", "source": "ca199.xlsx"},
        {"date": "2024-12-02", "value": 19.1, "flag": "↓", "source": "ca199.xlsx"},
        {"date": "2025-10-28", "value": 28.8, "flag": "↑", "source": "ca199.xlsx"}
      ]
    },
    "CA125": {
      "name": "糖类抗原 125",
      "unit": "U/ml",
      "ref_range": {"low": 0, "high": 35},
      "trend": [
        {"date": "2023-06-01", "value": 314, "flag": "↑", "source": "ca199.xlsx"},
        {"date": "2024-12-02", "value": 8.08, "flag": "正常", "source": "ca199.xlsx"}
      ]
    }
  }
}
```

### 5.3 blood_routine（血常规）

```json
{
  "blood_routine": {
    "WBC": {
      "name": "白细胞计数",
      "unit": "×10^9/L",
      "ref_range": {"low": 3.5, "high": 9.5},
      "trend": [
        {"date": "2025-09-22", "value": 7.0, "flag": "正常", "source": "IMG_2603.PNG"}
      ]
    },
    "HGB": {
      "name": "血红蛋白",
      "unit": "g/L",
      "ref_range": {"low": 130, "high": 175},
      "trend": [
        {"date": "2025-09-22", "value": 131, "flag": "正常", "source": "IMG_2603.PNG"}
      ]
    }
  }
}
```

### 5.4 liver_kidney（肝肾功能）

```json
{
  "liver_kidney": {
    "ALT": {"name": "丙氨酸氨基转移酶", "unit": "U/L", "ref_range": {"low": 0, "high": 40}, "trend": []},
    "AST": {"name": "天门冬氨酸氨基转移酶", "unit": "U/L", "ref_range": {"low": 0, "high": 40}, "trend": []},
    "Cr": {"name": "肌酐", "unit": "umol/L", "ref_range": {"low": 44, "high": 133}, "trend": [
      {"date": "2025-08-28", "value": 76, "flag": "正常", "source": "IMG_2603.PNG"}
    ]},
    "ALB": {"name": "白蛋白", "unit": "g/L", "ref_range": {"low": 40, "high": 55}, "trend": [
      {"date": "2023-07-01", "value": 35.4, "flag": "↓", "source": "2025-03-31_处方用药.JPG"}
    ]},
    "TBIL": {"name": "总胆红素", "unit": "umol/L", "ref_range": {"low": 0, "high": 26}, "trend": [
      {"date": "2025-08-28", "value": 18.5, "flag": "正常", "source": "IMG_2603.PNG"}
    ]}
  }
}
```

---

## 6. imaging（影像报告体系）

```json
{
  "imaging": [
    {
      "id": "img_001",
      "date": "2023-06-27",
      "modality": "PET-CT",
      "facility": "本院",
      "indication": "胰腺恶性肿瘤分期",
      "findings": [
        "胰头部 MT 伴远端胰管扩张",
        "腹腔淋巴结转移",
        "腹膜广泛转移伴腹盆腔积液",
        "脂肪肝"
      ],
      "conclusion": "胰腺头部 MT，腹腔及腹膜转移",
      "comparison": null,
      "radiologist": null,
      "report_no": null,
      "source_files": ["01 病情概述.pdf"],
      "dicom_metadata": {
        "patient_id": "11493391",
        "accession_no": "02241231216169",
        "study_date": "2024-12-31",
        "series_count": 4
      }
    },
    {
      "id": "img_002",
      "date": "2024-12-31",
      "modality": "CT",
      "facility": "本院",
      "indication": "复查",
      "findings": [
        "胰腺体尾部及脾脏已切除",
        "术区见结节状致密影",
        "残余胰头实质见结节状低密度影",
        "肝门区、腹膜后及肠系膜间隙多个小淋巴结"
      ],
      "conclusion": "胰腺术后表现，对比前片变化不大",
      "comparison": "2025-10-22",
      "source_files": ["IMG_0107.JPG"]
    }
  ]
}
```

---

## 7. pathology（病理报告体系）

```json
{
  "pathology": [
    {
      "id": "path_001",
      "date": "2023-06-30",
      "procedure": "腹腔镜探查+大网膜活检术",
      "facility": "本院",
      "specimen": [
        {"id": "1", "name": "网膜结节1", "size": null},
        {"id": "2", "name": "网膜结节2", "size": null}
      ],
      "findings": "大片粘液湖内见异型腺上皮，倾向粘液腺癌",
      "diagnosis": "转移/浸润性粘液腺癌",
      "grade": "中分化",
      "invasion": {
        "nerve": null,
        "vascular": null,
        "lymphatic": null,
        "perineural": null
      },
      "margin": {
        "pancreatic_cut": null,
        "bile_duct_cut": null,
        "gastric_cut": null
      },
      "lymph_nodes": {
        "examined": 0,
        "positive": 0,
        "notes": "淋巴结6枚未见癌转移(0/6)"
      },
      "ihc": [
        {"marker": "CK", "result": "+", "notes": null},
        {"marker": "CK19", "result": "+", "notes": null},
        {"marker": "Ki-67", "result": "20%+", "notes": null},
        {"marker": "DPC4", "result": "-", "notes": null}
      ],
      "molecular": null,
      "source_files": ["01 病情概述.pdf"]
    }
  ]
}
```

---

## 8. medications（用药方案细节）

```json
{
  "medications": [
    {
      "id": "med_001",
      "name": "AG方案",
      "generic_name": "白蛋白紫杉醇+吉西他滨",
      "type": "化疗",
      "category": "一线化疗",
      "start_date": "2023-07-11",
      "end_date": null,
      "current": true,
      "cycle_length_days": 21,
      "planned_cycles": null,
      "completed_cycles": 15,
      "regimen": [
        {
          "drug": "注射用紫杉醇(白蛋白结合型)",
          "dose": "180mg",
          "dose_unit": "mg",
          "route": "静滴",
          "frequency": "d1",
          "times_per_cycle": 1
        },
        {
          "drug": "注射用盐酸吉西他滨",
          "dose": "0.2g×8瓶",
          "dose_unit": "g",
          "route": "静滴",
          "frequency": "d1/d8/d15",
          "times_per_cycle": 3
        }
      ],
      "dose_adjustments": [],
      "response": [
        {"date": "2023-09-08", "assessment": "PR", "notes": "C3D1"},
        {"date": "2023-10-09", "assessment": "SD", "notes": "C4D1"},
        {"date": "2024-01-02", "assessment": "SD", "notes": "2024.01.02"},
        {"date": "2025-03-31", "assessment": "SD", "notes": "最新随访"}
      ],
      "toxicities": [
        {"date": "2024-01-03", "type": "神经毒性", "grade": "1", "description": "手脚麻木"}
      ],
      "supportive_meds": [
        {"drug": "乳果糖口服溶液", "dose": "20ml", "route": "口服", "frequency": "BID", "purpose": "通便"}
      ],
      "source_files": ["2025-03-31_处方用药.JPG"]
    }
  ]
}
```

---

## 9. surgeries（手术记录）

```json
{
  "surgeries": [
    {
      "id": "surg_001",
      "date": "2023-06-30",
      "procedure": "腹腔镜探查+大网膜活检术",
      "approach": "腹腔镜",
      "findings": "胰头部MT，腹腔及腹膜转移",
      "specimen_removed": ["网膜结节1", "网膜结节2"],
      "blood_loss_ml": null,
      "complications": null,
      "hospital": "本院",
      "source_files": ["01 病情概述.pdf"]
    },
    {
      "id": "surg_002",
      "date": "2024-12-17",
      "procedure": "腹腔镜下根治性顺行模块化胰体尾+脾脏切除术",
      "approach": "腹腔镜",
      "findings": "胰腺大小9*4*3cm，肿块3*2*1.5cm",
      "specimen_removed": ["胰体尾", "脾脏", "周围淋巴结"],
      "blood_loss_ml": null,
      "complications": null,
      "hospital": "西南医院",
      "source_files": ["病 情 介 绍.doc"]
    }
  ]
}
```

---

## 10. treatment_history（治疗经过时间线）

```json
{
  "treatment_history": [
    {
      "phase": "术前评估",
      "start_date": "2023-06-23",
      "end_date": "2023-06-27",
      "treatments": ["超声", "CT", "PET-CT"],
      "outcome": "确诊胰腺恶性肿瘤伴腹膜转移"
    },
    {
      "phase": "一线化疗",
      "regimen": "AG方案",
      "start_date": "2023-07-11",
      "end_date": null,
      "cycles": 15,
      "response": "SD（疾病稳定）",
      "toxicities": ["手脚麻木"],
      "source_files": ["2025-03-31_处方用药.JPG"]
    }
  ]
}
```

---

## 11. supportive_care（支持治疗体系）

支持治疗是胰腺癌患者管理的重要组成部分，包含营养支持、并发症管理和心理支持三大模块。

```json
{
  "supportive_care": {
    "nutrition": { ... },
    "complications": { ... },
    "psychological": { ... }
  }
}
```

### 11.1 nutrition（营养支持）

```json
{
  "nutrition": {
    "assessment": {
      "weight_kg": 57,
      "height_cm": 152,
      "bmi": 24.6,
      "bmi_category": "正常",
      "weight_change_3m_kg": -5,
      "weight_change_3m_percent": -8.1,
      "nutritional_risk_score": "中度",
      "assessment_date": "2026-01-04",
      "assessment_tool": "NRS-2002"
    },
    "biochemical_markers": {
      "albumin": {
        "name": "白蛋白",
        "abbr": "ALB",
        "unit": "g/L",
        "ref_range": {"low": 35, "high": 50},
        "clinical_significance": "反映营养状态和肝功能，半衰期约21天",
        "grading": {
          "normal": {"low": 35, "high": 50},
          "mild": {"low": 30, "high": 35},
          "moderate": {"low": 25, "high": 30},
          "severe": {"low": 0, "high": 25}
        },
        "trend": [
          {"date": "2023-07-01", "value": 35.4, "flag": "↓", "grade": "轻度", "source": "2025-03-31_处方用药.JPG"}
        ]
      },
      "prealbumin": {
        "name": "前白蛋白",
        "abbr": "PAB",
        "unit": "mg/L",
        "ref_range": {"low": 180, "high": 360},
        "clinical_significance": "半衰期短(2-3天)，反映急性期营养状态变化",
        "grading": {
          "normal": {"low": 180, "high": 360},
          "mild": {"low": 150, "high": 180},
          "moderate": {"low": 100, "high": 150},
          "severe": {"low": 0, "high": 100}
        },
        "trend": []
      },
      "hemoglobin": {
        "name": "血红蛋白",
        "abbr": "HGB",
        "unit": "g/L",
        "ref_range": {"low": 130, "high": 175},
        "clinical_significance": "评估贫血程度，影响患者生活质量及化疗耐受性",
        "grading": {
          "normal": {"low": 130, "high": 175},
          "grade1": {"low": 90, "high": 120, "description": "轻度贫血"},
          "grade2": {"low": 60, "high": 90, "description": "中度贫血"},
          "grade3": {"low": 30, "high": 60, "description": "重度贫血"},
          "grade4": {"low": 0, "high": 30, "description": "极重度贫血"}
        },
        "trend": []
      },
      "total_protein": {
        "name": "总蛋白",
        "abbr": "TP",
        "unit": "g/L",
        "ref_range": {"low": 65, "high": 85},
        "trend": []
      },
      "cholesterol": {
        "name": "总胆固醇",
        "abbr": "TC",
        "unit": "mmol/L",
        "ref_range": {"low": 3.0, "high": 5.7},
        "clinical_significance": "胰腺癌患者常伴发高脂血症，影响药物代谢",
        "trend": []
      },
      "triglyceride": {
        "name": "甘油三酯",
        "abbr": "TG",
        "unit": "mmol/L",
        "ref_range": {"low": 0.56, "high": 1.7},
        "trend": []
      },
      "glucose": {
        "name": "空腹血糖",
        "abbr": "GLU",
        "unit": "mmol/L",
        "ref_range": {"low": 3.9, "high": 6.1},
        "clinical_significance": "新发糖尿病是胰腺癌的早期表现之一",
        "trend": []
      },
      "rbc": {
        "name": "红细胞计数",
        "abbr": "RBC",
        "unit": "×10^12/L",
        "ref_range": {"low": 4.3, "high": 5.8},
        "trend": []
      }
    },
    "recommendations": []
  }
}
```

### 11.2 complications（并发症管理与风险提示）

监测胰腺癌患者常见的 6 大并发症，每个并发症包含风险等级、监测指标和临床意义。

```json
{
  "complications": {
    "gi_bleeding": {
      "name": "消化道出血",
      "icd10": "K92.2",
      "risk_level": "low",
      "monitoring_indicators": {
        "hemoglobin": {
          "name": "血红蛋白",
          "abbr": "HGB",
          "unit": "g/L",
          "clinical_significance": "评估贫血程度，反映出血严重程度",
          "grading": {
            "normal": {"low": 120, "high": 160, "description": "正常"},
            "grade1": {"low": 90, "high": 120, "description": "轻度贫血（血红蛋白90-120g/L）"},
            "grade2": {"low": 60, "high": 90, "description": "中度贫血（血红蛋白60-90g/L）"},
            "grade3": {"low": 30, "high": 60, "description": "重度贫血（血红蛋白30-60g/L）"},
            "grade4": {"low": 0, "high": 30, "description": "极重度贫血（血红蛋白<30g/L）"}
          },
          "trend": []
        },
        "fecal_occult_blood": {
          "name": "粪便隐血",
          "abbr": "FOBT",
          "unit": null,
          "ref_range": "阴性",
          "clinical_significance": "监测消化道微量出血，阳性提示活动性出血",
          "trend": []
        },
        "stool_color": {
          "name": "大便性状",
          "unit": null,
          "abnormal_values": ["黑便", "柏油样便", "血便", "暗红色便"],
          "clinical_significance": "黑便提示上消化道出血，血便提示下消化道出血",
          "trend": []
        }
      },
      "symptoms": ["黑便", "呕血", "头晕", "心悸", "血压下降", "面色苍白"],
      "risk_factors": ["化疗（黏膜炎）", "肿瘤侵犯", "凝血功能障碍", "NSAIDs使用"],
      "last_assessment": null,
      "source_files": []
    },
    "biliary_obstruction": {
      "name": "胆道梗阻",
      "icd10": "K83.1",
      "risk_level": "medium",
      "monitoring_indicators": {
        "total_bilirubin": {
          "name": "总胆红素",
          "abbr": "TBIL",
          "unit": "umol/L",
          "ref_range": {"low": 3.4, "high": 17.1},
          "clinical_significance": "梗阻性黄疸的标志，肿瘤压迫胆总管时升高",
          "grading": {
            "normal": {"low": 3.4, "high": 17.1},
            "mild": {"low": 17.1, "high": 34.2, "description": "隐性黄疸"},
            "moderate": {"low": 34.2, "high": 171, "description": "轻度黄疸"},
            "severe": {"low": 171, "high": 342, "description": "中度黄疸"},
            "critical": {"low": 342, "high": 9999, "description": "重度黄疸"}
          },
          "trend": []
        },
        "direct_bilirubin": {
          "name": "直接胆红素",
          "abbr": "DBIL",
          "unit": "umol/L",
          "ref_range": {"low": 0, "high": 6.8},
          "clinical_significance": "升高提示梗阻性黄疸",
          "trend": []
        },
        "alp": {
          "name": "碱性磷酸酶",
          "abbr": "ALP",
          "unit": "U/L",
          "ref_range": {"low": 45, "high": 125},
          "clinical_significance": "胆汁淤积的敏感指标",
          "grading": {
            "normal": {"low": 45, "high": 125},
            "mild": {"low": 125, "high": 300, "description": "轻度升高"},
            "moderate": {"low": 300, "high": 500, "description": "中度升高"},
            "severe": {"low": 500, "high": 9999, "description": "重度升高"}
          },
          "trend": []
        },
        "ggt": {
          "name": "γ-谷氨酰转肽酶",
          "abbr": "GGT",
          "unit": "U/L",
          "ref_range": {"low": 10, "high": 60},
          "clinical_significance": "胆道梗阻的特异性指标",
          "grading": {
            "normal": {"low": 10, "high": 60},
            "mild": {"low": 60, "high": 120, "description": "轻度升高"},
            "moderate": {"low": 120, "high": 300, "description": "中度升高"},
            "severe": {"low": 300, "high": 9999, "description": "重度升高"}
          },
          "trend": []
        }
      },
      "symptoms": ["黄疸", "皮肤瘙痒", "尿色加深（浓茶色）", "陶土样便", "腹痛"],
      "imaging": ["超声", "CT", "MRCP"],
      "risk_factors": ["肿瘤进展", "胆管侵犯", "淋巴结转移"],
      "last_assessment": null,
      "source_files": []
    },
    "bowel_obstruction": {
      "name": "肠梗阻",
      "icd10": "K56.0",
      "risk_level": "low",
      "monitoring_indicators": {},
      "symptoms": [
        "腹痛（阵发性绞痛）",
        "腹胀（腹部膨隆，肠型可见）",
        "呕吐（早期反射性，晚期反流性）",
        "停止排气排便",
        "腹部膨隆"
      ],
      "imaging": {
        "modality": "腹部立位X线平片 / CT",
        "findings": ["气液平面", "肠管扩张（>3cm）", "阶梯状液平", "梗阻点"],
        "clinical_significance": "机械性梗阻 vs 麻痹性梗阻的鉴别"
      },
      "risk_factors": ["肿瘤进展", "腹腔粘连", "腹水", "低钾血症"],
      "last_assessment": null,
      "source_files": []
    },
    "pancreatitis": {
      "name": "胰腺炎",
      "icd10": "K85.9",
      "risk_level": "medium",
      "monitoring_indicators": {
        "amylase": {
          "name": "淀粉酶",
          "abbr": "AMY",
          "unit": "U/L",
          "ref_range": {"low": 35, "high": 135},
          "clinical_significance": ">正常值3倍提示急性胰腺炎",
          "trend": []
        },
        "lipase": {
          "name": "脂肪酶",
          "abbr": "LIP",
          "unit": "U/L",
          "ref_range": {"low": 13, "high": 60},
          "clinical_significance": "特异性高于淀粉酶",
          "trend": []
        },
        "crp": {
          "name": "C反应蛋白",
          "abbr": "CRP",
          "unit": "mg/L",
          "ref_range": {"low": 0, "high": 8},
          "clinical_significance": "炎症标志物，评估炎症程度",
          "trend": []
        },
        "wbc": {
          "name": "白细胞计数",
          "abbr": "WBC",
          "unit": "×10^9/L",
          "ref_range": {"low": 3.5, "high": 9.5},
          "clinical_significance": "感染/炎症指标",
          "trend": []
        }
      },
      "symptoms": ["上腹痛", "恶心", "呕吐", "发热", "腹胀", "压痛"],
      "risk_factors": ["ERCP", "胆道梗阻", "酒精", "高脂血症", "化疗药物"],
      "last_assessment": null,
      "source_files": []
    },
    "infection": {
      "name": "感染",
      "icd10": "A49.9",
      "risk_level": "medium",
      "monitoring_indicators": {
        "pct": {
          "name": "降钙素原",
          "abbr": "PCT",
          "unit": "ng/ml",
          "ref_range": {"low": 0, "high": 0.05},
          "clinical_significance": "细菌感染的特异性标志物，>0.5提示感染",
          "grading": {
            "normal": {"low": 0, "high": 0.05},
            "suspected": {"low": 0.05, "high": 0.5, "description": "可疑感染"},
            "likely": {"low": 0.5, "high": 2.0, "description": "可能感染"},
            "severe": {"low": 2.0, "high": 9999, "description": "严重感染"}
          },
          "trend": []
        },
        "crp": {
          "name": "C反应蛋白",
          "abbr": "CRP",
          "unit": "mg/L",
          "ref_range": {"low": 0, "high": 8},
          "clinical_significance": "炎症指标，>10提示感染",
          "trend": []
        },
        "ssa": {
          "name": "血清淀粉样蛋白A",
          "abbr": "SSA",
          "unit": "mg/L",
          "ref_range": {"low": 0, "high": 10},
          "clinical_significance": "急性期反应蛋白，炎症早期指标",
          "trend": []
        },
        "cps": {
          "name": "CPS（临床肺炎评分）",
          "abbr": "CPS",
          "unit": null,
          "ref_range": null,
          "clinical_significance": "评估肺部感染严重程度",
          "trend": []
        },
        "bacterial_culture": {
          "name": "细菌培养",
          "abbr": "BC",
          "unit": null,
          "ref_range": "无菌生长",
          "clinical_significance": "确定病原体，指导抗生素选择",
          "trend": []
        }
      },
      "symptoms": ["发热", "寒战", "咳嗽咳痰", "尿频尿急", "局部红肿", "意识改变"],
      "risk_factors": ["化疗（中性粒细胞减少）", "中心静脉置管", "胆道梗阻", "糖尿病"],
      "last_assessment": null,
      "source_files": []
    },
    "thrombosis": {
      "name": "血栓风险",
      "icd10": "I82.9",
      "risk_level": "medium",
      "monitoring_indicators": {
        "d_dimer": {
          "name": "D-二聚体",
          "abbr": "D-dimer",
          "unit": "mg/L",
          "ref_range": {"low": 0, "high": 0.5},
          "clinical_significance": "血栓形成的敏感指标，但特异性低",
          "grading": {
            "normal": {"low": 0, "high": 0.5},
            "low_risk": {"low": 0.5, "high": 1.0, "description": "低风险"},
            "medium_risk": {"low": 1.0, "high": 2.0, "description": "中风险"},
            "high_risk": {"low": 2.0, "high": 9999, "description": "高风险"}
          },
          "trend": []
        },
        "pt": {
          "name": "凝血酶原时间",
          "abbr": "PT",
          "unit": "s",
          "ref_range": {"low": 11, "high": 13.5},
          "clinical_significance": "评估外源性凝血途径",
          "trend": []
        },
        "aptt": {
          "name": "活化部分凝血活酶时间",
          "abbr": "APTT",
          "unit": "s",
          "ref_range": {"low": 25, "high": 35},
          "clinical_significance": "评估内源性凝血途径",
          "trend": []
        },
        "fib": {
          "name": "纤维蛋白原",
          "abbr": "FIB",
          "unit": "g/L",
          "ref_range": {"low": 2.0, "high": 4.0},
          "clinical_significance": "升高提示高凝状态",
          "trend": []
        }
      },
      "symptoms": ["下肢浮肿", "单侧肢体肿胀", "胸痛", "呼吸困难", "皮肤发绀", "浅静脉曲张"],
      "risk_factors": ["恶性肿瘤", "化疗", "卧床", "中心静脉置管", "手术"],
      "last_assessment": null,
      "source_files": []
    }
  }
}
```

### 11.3 psychological（心理支持）

```json
{
    "psychological": {
      "screenings": [
        {
          "id": "psy_001",
          "date": null,
          "tool": "PHQ-9",
          "full_name": "患者健康问卷-9项",
          "score": null,
          "severity": null,
          "interpretation": null,
          "source_file": null,
          "scoring_guide": {
            "0_4": "无抑郁（正常）",
            "5_9": "轻度抑郁",
            "10_14": "中度抑郁",
            "15_19": "中重度抑郁",
            "20_27": "重度抑郁"
          },
          "monitoring_frequency": "每2-4周筛查一次，治疗期间每月评估"
        },
        {
          "id": "psy_002",
          "date": null,
          "tool": "GAD-7",
          "full_name": "广泛性焦虑量表",
          "score": null,
          "severity": null,
          "interpretation": null,
          "source_file": null,
          "scoring_guide": {
            "0_4": "无焦虑（正常）",
            "5_9": "轻度焦虑",
            "10_14": "中度焦虑",
            "15_21": "重度焦虑"
          },
          "monitoring_frequency": "每2-4周筛查一次"
        },
        {
          "id": "psy_003",
          "date": null,
          "tool": "HAMD",
          "full_name": "汉密尔顿抑郁量表",
          "score": null,
          "severity": null,
          "interpretation": null,
          "source_file": null,
          "scoring_guide": {
            "0_7": "正常",
            "8_17": "轻度抑郁",
            "18_24": "中度抑郁",
            "25_30": "重度抑郁",
            ">30": "极重度抑郁"
          },
          "monitoring_frequency": "初诊时基线评估，治疗后每4周评估"
        }
      ],
      "tools": {
        "phq9": {
          "name": "PHQ-9 抑郁症筛查量表",
          "items": 9,
          "scoring": {
            "0_4": "无抑郁（正常）",
            "5_9": "轻度抑郁",
            "10_14": "中度抑郁",
            "15_19": "中重度抑郁",
            "20_27": "重度抑郁"
          }
        },
        "gad7": {
          "name": "GAD-7 焦虑筛查量表",
          "items": 7,
          "scoring": {
            "0_4": "无焦虑（正常）",
            "5_9": "轻度焦虑",
            "10_14": "中度焦虑",
            "15_21": "重度焦虑"
          }
        },
        "hamd": {
          "name": "汉密尔顿抑郁量表",
          "items": 17,
          "scoring": {
            "0_7": "正常",
            "8_17": "轻度抑郁",
            "18_24": "中度抑郁",
            ">24": "重度抑郁"
          }
        }
      },
      "concerns": [],
      "support_history": [],
      "recommendations": []
    }
}
```

---

## 11. follow_up（随访记录）

```json
{
  "follow_up": [
    {
      "date": "2025-03-31",
      "type": "门诊",
      "department": "胰腺胆道",
      "hospital": "本院",
      "chief_complaint": "胰腺恶性肿瘤",
      "physical_exam": "一般情况可",
      "plan": "继续原方案化疗，对症支持治疗",
      "source_files": ["2025-03-31_处方用药.JPG"]
    }
  ]
}
```

---

## 12. alerts（警示引擎输出）

```json
{
  "alerts": [
    {
      "id": "alert_001",
      "level": "critical",
      "category": "lab_trend",
      "message": "CA199 从 342（2023-06）降至 19.1（2024-12），治疗后好转；但 2025-10 回升至 28.8，2025-11 为 28.3",
      "date": "2025-10-28",
      "action": "建议与主治医生沟通，必要时影像复查",
      "source_data": ["ca199.xlsx"]
    },
    {
      "id": "alert_002",
      "level": "warning",
      "category": "toxicity",
      "message": "化疗副作用：手脚麻木（2024-01-03 起），可能为紫杉醇神经毒性",
      "date": "2024-01-03",
      "action": "下次就诊可咨询是否需调整剂量或加用营养神经药物",
      "source_data": ["2025-03-31_处方用药.JPG"]
    },
    {
      "id": "alert_003",
      "level": "info",
      "category": "genetic",
      "message": "基因检测提示 ATM、VEGFR 突变，KRAS 野生型",
      "date": "2023-07-06",
      "action": "可考虑参加 KRAS 野生型胰腺癌临床试验",
      "source_data": ["01 病情概述.pdf"]
    }
  ]
}
```

### alert.level 定义

| level | 含义 | 触发条件示例 |
|-------|------|-------------|
| `critical` | 危急值/紧急 | 血钾 <2.5 或 >6.5、血红蛋白 <60、CA199 持续快速上升 |
| `warning` | 需关注 | 化疗副作用累积、肿瘤标志物回升、新发症状 |
| `info` | 仅供参考 | 基因突变提示、治疗节点、建议复查 |

---

## 13. recommendations（建议引擎输出）

```json
{
  "recommendations": {
    "immediate": [
      {
        "priority": "high",
        "category": "follow_up",
        "message": "CA199 近期回升至 28.8（参考值 0-37），建议下次就诊时复查影像",
        "based_on": "lab_trend_analysis"
      }
    ],
    "next_visit": [
      {
        "priority": "medium",
        "category": "medication",
        "message": "手脚麻木持续，咨询是否需调整紫杉醇剂量或加用营养神经药物",
        "based_on": "toxicity_record"
      },
      {
        "priority": "medium",
        "category": "genetic",
        "message": "当前 KRAS 野生型，可询问是否有适合的临床试验",
        "based_on": "genetic_profile"
      }
    ],
    "lifestyle": [
      {
        "priority": "low",
        "category": "nutrition",
        "message": "ALB 最低 35.4g/L（偏低），注意蛋白质摄入",
        "based_on": "lab_trend_analysis"
      }
    ]
  }
}
```

---

## 14. data_sources（数据血缘）

```json
{
  "data_sources": {
    "total_files": 274,
    "extracted_files": 246,
    "failed_files": 2,
    "last_updated": "2026-06-22T18:00:00+00:00",
    "mineru_batches": [
      {"batch_id": "442e41d3...", "file_count": 50, "status": "completed"},
      {"batch_id": "3be4193c...", "file_count": 50, "status": "completed"}
    ],
    "file_registry": [
      {
        "hash": "6819e19b...",
        "original_name": "01 病情概述.pdf",
        "category": "clinical_records",
        "extracted_path": "data/extracted/01_病情概述.md",
        "date_detected": "2023-06-23"
      }
    ]
  }
}
```

---

## 设计原则

1. **Schema 比报告更完整**：报告只展示必要信息，Schema 保留全部原始数据（如所有检验值、完整影像结论）
2. **数据血缘可追溯**：每个字段都记录 `source_files`，方便回溯原始材料
3. **时间序列优先**：检验指标、用药、随访全部以时间序列存储，方便趋势分析
4. **可扩展**：新增实体类型（如放疗、免疫治疗）只需在顶层加数组，不影响现有结构
5. **双视图友好**：医护版直接序列化 Schema，患者版通过模板引擎选择性投影

---

## 与模板字段映射

| 模板字段 | Schema 路径 |
|---------|------------|
| 基本信息 | `demographics` |
| 主诉 | `chief_complaint` |
| 确诊情况 | `diagnoses[0]` |
| 影像学检查 | `imaging[]` |
| 病理检查 | `pathology[0]` |
| 分子检测 | `genetic_profile.tests[0]` |
| 手术治疗 | `surgeries[]` |
| 化疗情况 | `medications[]` + `treatment_history[]` |
| 随访情况 | `follow_up[]` + `lab_tests` |
| 总结评估 | 自动生成（基于 alerts） |
| 后续建议 | `recommendations` |
| 营养支持 | `supportive_care.nutrition` |
| 并发症管理 | `supportive_care.complications.{gi_bleeding,biliary_obstruction,bowel_obstruction,pancreatitis,infection,thrombosis}` |
| 心理支持 | `supportive_care.psychological` |
