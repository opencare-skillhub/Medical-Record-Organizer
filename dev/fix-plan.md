# 三链路修复计划

> 基于 2026-06-23 全链路审查报告。
> 修复顺序按阻塞关系排列：先修数据契约 → 再修管道逻辑 → 最后修渲染输出。

---

## A. 前置：统一数据契约（阻塞后续所有任务）

### A1. 定义并文档化 Map 阶段的标准输出 Schema

- **问题**：`MAP_SCHEMA` 输出的字段名与 Shuffle/Reduce 期望的字段名不一致（`file_type` vs `report_type`，`lab_tests.tumor_markers` vs `lab_values`）。
- **修复要求**：
  1. 在 `dev/docs/data-contract.md` 中定义 Map 输出的标准 JSON Schema，明确每个字段的类型、必填性、示例值。
  2. 统一命名：`file_type` 改为 `report_type`；Map 输出增加顶层 `lab_values` 数组（展平格式），同时保留 `lab_tests` 嵌套结构供下游按需使用。
  3. `lab_values` 每项包含：`name`, `value`, `unit`, `date`, `ref_low`, `ref_high`, `abnormal`（布尔）。
  4. 同步更新 `map_extract.py` 的 `MAP_SCHEMA` 和 `SYSTEM_PROMPT`。
- **测试方法**：用 `test_map_extract.py` 中 mock 数据验证输出 JSON 的 key 与 data-contract.md 一致；跑 `pytest tests/v2/test_map_extract.py -v`。
- **影响范围**：`map_extract.py`, `shuffle_group.py`, `data-contract.md`（新建）。

### A2. 定义并文档化 HTML 模板的 Context 数据模型

- **问题**：`html-report-template.html` 引用的 `compute_report_context()` 不存在，模板变量与 `PatientProfile` 模型全面不匹配。
- **修复要求**：
  1. 在 `dev/docs/template-context.md` 中定义模板所需的所有 context 变量名、类型、来源（从 PatientProfile 的哪个字段转换而来）。
  2. 列出缺失的转换逻辑（如 `genetic_highlights` 需要从 `GeneticProfile.tests` + `Pathology.ihc` 构建；`tumor_marker_tables` 需要从 `LabTests.tumor_markers` 的 trend 计算 change 和 note）。
  3. 标记模板中胰腺癌特定的硬编码文本，供后续通用化处理。
- **测试方法**：人工 review template-context.md 与 `html-report-template.html` 中的所有 `{{ }}` 变量一一对应。
- **影响范围**：`template-context.md`（新建），`html-report-template.html`（仅标注，不修改）。

---

## B. OCR 提取链路

### B1. 修复 PDF 双重打开与资源泄漏

- **文件**：`scripts/ocr_siliconflow.py`，`detect_pdf_type()` 函数（L138–149）
- **修复要求**：
  1. 只打开一次 PDF，在关闭前获取 page_count。
  2. 使用 `with fitz.open(pdf_path) as doc:` 上下文管理器（PyMuPDF 支持）。
- **测试方法**：
  ```bash
  python3 -c "
  from scripts.ocr_siliconflow import detect_pdf_type
  info = detect_pdf_type('test_data/sample.pdf')
  assert 'page_count' in info and info['page_count'] > 0
  print('OK')
  "
  ```

### B2. MinerU 健康检查逻辑修正

- **文件**：`scripts/extract_mineru.py`，`check_config()` 函数（L39–56）
- **修复要求**：
  1. 404 响应应视为配置失败（除非用户显式设置 `MINERU_SKIP_HEALTH_CHECK=true`）。
  2. 只有 200 才确认 API 可访问；其他状态码打印警告但不阻断。
- **测试方法**：
  ```bash
  # 模拟不可达 URL
  MINERU_API_URL=https://httpstat.us/404 python3 scripts/extract_mineru.py --check-config
  # 预期：exit code != 0
  ```

### B3. OCR 大图提前拒绝（可选但推荐）

- **文件**：`scripts/ocr_siliconflow.py`，`_encode_image()` 函数（L86–88）
- **修复要求**：超过 10MB 的图片直接 `sys.exit(1)` 并提示压缩后再试，而不是警告后继续。
- **测试方法**：创建一个 >10MB 的假图片文件，确认脚本 exit code != 0。

---

## C. MapReduce 链路

### C1. `group_by_type()` 字段名修正

- **文件**：`scripts/v2/shuffle_group.py`，L9
- **修复要求**：`item.get("report_type", "other")` → 确认与 MAP_SCHEMA 输出一致（见 A1 修复后应为 `report_type`）。
- **测试方法**：
  ```python
  # tests/v2/test_shuffle_group.py
  def test_group_by_type_uses_report_type():
      from scripts.v2.shuffle_group import group_by_type
      extracted = [
          {"report_type": "lab_results", "report_date": "2025-01-01"},
          {"report_type": "imaging", "report_date": "2025-02-01"},
      ]
      groups = group_by_type(extracted)
      assert "lab_results" in groups
      assert "imaging" in groups
      assert "other" not in groups
  ```

### C2. `merge_lab_trends()` 适配统一的 `lab_values` 结构

- **文件**：`scripts/v2/shuffle_group.py`，`merge_lab_trends()` 函数（L16–41）
- **修复要求**：
  1. 按 A1 修复后的 `lab_values` 数组读取数据。
  2. 增加防御：如果 `lab_values` 为空，回退尝试 `lab_tests.tumor_markers` 等嵌套结构。
  3. 趋势条目增加 `flag` 字段（根据 value vs ref_range 计算）。
- **测试方法**：
  ```python
  def test_merge_lab_trends_from_lab_values():
      from scripts.v2.shuffle_group import merge_lab_trends
      lab_group = [{
          "report_date": "2025-01-01",
          "lab_values": [
              {"name": "CA199", "value": 100, "unit": "U/ml", "ref_low": 0, "ref_high": 37, "abnormal": True},
          ]
      }]
      trends = merge_lab_trends(lab_group)
      assert "CA199" in trends
      assert trends["CA199"]["ref_range"] == (0, 37)
      assert len(trends["CA199"]["trend"]) == 1
  ```

### C3. 实现 `reduce_medication_history()` 和 `reduce_imaging_narrative()`

- **文件**：`scripts/v2/reduce_merge.py`，L58–65
- **修复要求**：
  1. `reduce_medication_history()`：从 Map 提取的 medications 数组中按 `start_date` 排序，去重合并（同药名+同期 → 合并），输出 `[{name, type, start_date, end_date, cycles}]` 时间线。
  2. `reduce_imaging_narrative()`：按 `date` 排序影像记录，对相邻两次检查生成"对比前片"叙事（如 "较前增大/缩小/稳定"），使用 LLM 调用。
  3. 在 `pipeline_v2.py` 的 `assemble_profile()` 中使用这两个 Reduce 结果。
- **测试方法**：
  ```python
  def test_reduce_medication_dedup():
      from scripts.v2.reduce_merge import reduce_medication_history
      med_group = [
          {"medications": [{"name": "奥希替尼", "start_date": "2025-01-01", "type": "靶向"}]},
          {"medications": [{"name": "奥希替尼", "start_date": "2025-01-01", "type": "靶向"}]},
      ]
      result = reduce_medication_history(med_group)
      assert len(result.get("timeline", [])) == 1  # 去重
  ```

### C4. LLM 模型调用增加降级链

- **文件**：`scripts/v2/llm_client.py`，`call_llm_with_retry()` 函数（L176–191）
- **修复要求**：
  1. `call_llm_with_retry` 改为遍历 `MODEL_PRIORITY` 列表，每个模型尝试 `max_retries` 次后降级到下一个。
  2. `chat_json()` 的模型回退逻辑与 `call_llm_with_retry` 统一。
- **测试方法**：
  ```python
  def test_model_fallback_on_failure(monkeypatch):
      # 模拟前两个模型失败，第三个成功
      ...
      assert result is not None
  ```

### C5. `alert_level` 字符串规范化

- **文件**：`scripts/v2/pipeline_v2.py`，`_build_alerts()` 函数（L83–98）
- **修复要求**：
  1. 对 LLM 返回的 `alert_level` 做 `.lower().strip()` 处理。
  2. 增加别名映射：`{"high": "critical", "elevated": "warning", "abnormal": "warning"}`。
- **测试方法**：
  ```python
  def test_alert_level_normalization():
      from scripts.v2.pipeline_v2 import _build_alerts
      lab_analysis = {"CA199": {"alert_level": "Warning", "trend_summary": "上升"}}
      alerts = _build_alerts({}, lab_analysis)
      assert len(alerts) >= 1
  ```

### C6. 脱敏映射持久化

- **文件**：`scripts/v2/pipeline_v2.py`，`run_pipeline()` 函数（L208–228）
- **修复要求**：
  1. 在 Map 阶段将 `mapping` 写入 `output_dir/mappings.json`（增量合并）。
  2. 将脱敏后的文本写入 `sanitized_dir/{original_name}.sanitized.md`。
  3. 管道中断后重新运行时，从 `mappings.json` 恢复已有映射。
- **测试方法**：
  ```python
  def test_mapping_persisted(tmp_path):
      # 跑一次 pipeline → 检查 mappings.json 存在
      # 再跑一次 → 确认映射被追加而非覆盖
  ```

### C7. 增量更新路径比对修正

- **文件**：`scripts/v2/pipeline_v2.py`，`_file_key()` 和 `run_pipeline()`（L165–169, L209–212）
- **修复要求**：
  1. manifest 中统一存储 `Path(file_path).resolve()` 作为 key。
  2. 或者在比对时两端都做 `resolve()`。
- **测试方法**：
  ```python
  def test_incremental_with_relative_path(tmp_path):
      # 用相对路径跑第一次 → 用相同相对路径跑第二次
      # 确认 skipped_files = 1
  ```

### C8. LLM 文本截断改为智能截断

- **文件**：`scripts/v2/llm_client.py`，`extract_structured()` 函数（L172）
- **修复要求**：
  1. 改为 `text[:12000]` 或根据模型 context window 动态截断。
  2. 截断时优先保留开头（通常包含报告类型和关键指标）和结尾（通常包含结论）。
  3. 被截断时在 user_prompt 中加 `[文本已截断，原始长度 {len(text)} 字符]` 标记。
- **测试方法**：构造 >8000 字符的文本，验证 prompt 中包含截断标记。

### C9. `_build_supportive_care()` 使用真实数据

- **文件**：`scripts/v2/pipeline_v2.py`，`_build_supportive_care()` 函数（L135–145）
- **修复要求**：
  1. 不从空 PatientProfile 构建，改为直接传入 `profile`（在 `assemble_profile` 中已有完整 profile）。
  2. 并发症风险等级应动态调用 `analysis_engine.py` 中的评估函数，而非硬编码 `"low"` / `"medium"`。
- **测试方法**：用真实数据跑 `assemble_profile`，检查 `profile.supportive_care.complications` 中各并发症的 `risk_level` 是否根据 lab 数据变化。

---

## D. HTML 模板链路

### D1. 实现 `compute_report_context()` 函数

- **文件**：新建 `scripts/v2/render_html.py`
- **修复要求**：
  1. 输入：`PatientProfile` 实例。
  2. 输出：与 `html-report-template.html` 的 Jinja2 context 完全匹配的 dict。
  3. 包含所有转换逻辑：
     - `demographics` → 模板期望的 flat dict（增加 `past_history`, `primary_diagnosis`, `icd_code` 等缺失字段的默认空值）。
     - `timeline` → 从 profile 和 manifest 数据构建 `[{dates, title, category, note}]` 结构。
     - `pathology` → 转换为 `[{label, type, date, summary, findings, value, is_critical}]`。
     - `genetic_highlights` → 合并 `GeneticProfile.tests` 和 `Pathology.ihc`。
     - `medication_summary` + `medication_table` → 从 `Medication` 列表转换。
     - `tumor_marker_tables` → 从 `LabTests.tumor_markers` 计算 trend、change、note。
     - `chart_svg_ca199` → 用 `matplotlib` 或纯字符串模板生成 SVG 折线图。
     - `has_critical` + `critical_alerts` → 从 `alerts` 列表筛选 level=="critical"。
     - `key_concerns`, `consultation_questions` → 从 alerts 和 recommendations 生成。
  4. 使用 Jinja2 渲染模板并写入 `output/report.html`。
- **测试方法**：
  ```python
  def test_compute_report_context():
      profile = make_sample_profile()  # 构造完整 PatientProfile
      from scripts.v2.render_html import compute_report_context
      ctx = compute_report_context(profile)
      # 验证所有模板变量存在
      assert "demographics" in ctx
      assert "timeline" in ctx
      assert "tumor_marker_tables" in ctx
      assert "has_critical" in ctx
      # ... 逐项验证
  ```

### D2. HTML 模板通用化（去胰腺癌硬编码）

- **文件**：`w9a7d/references/html-report-template.html`
- **修复要求**：
  1. 标题 "胰腺肿瘤患者病情概览" → `{{ report_title | default('患者病情概览') | e }}`。
  2. 所有胰腺癌特定术语改为变量注入。
  3. 补充 `.card.gray` 的 CSS 样式。
- **测试方法**：用非胰腺癌数据渲染 HTML，确认标题和术语通用。

### D3. 添加 Jinja2 依赖并在管道中调用 HTML 渲染

- **文件**：`requirements.txt`，`scripts/v2/pipeline_v2.py`
- **修复要求**：
  1. `requirements.txt` 添加 `jinja2>=3.1.0`。
  2. `pipeline_v2.py:run_pipeline()` 末尾调用 `render_html.render_html_report(profile, output_dir)`。
- **测试方法**：跑完整的 `test_run_pipeline_creates_output_files`，确认 `report.html` 存在且内容有效。

---

## E. 集成与回归测试

### E1. 端到端测试

- **文件**：`tests/v2/test_e2e.py`（可能已存在同名文件，检查后新建或补充）
- **修复要求**：
  1. 用一组最小测试数据（1 个化验单 md + 1 个影像 md + 1 个用药 md）跑完整 `run_pipeline()`。
  2. 验证：无异常、`failed_files` 为空、输出文件存在。
  3. 验证 HTML 输出可通过 W3C validator 的基本检查（无未闭合标签）。
- **测试方法**：`pytest tests/v2/test_e2e.py -v`

### E2. 数据契约一致性检查

- **文件**：新建 `tests/v2/test_data_contract.py`
- **修复要求**：
  1. 自动比对 MAP_SCHEMA 输出示例与 Shuffle/Reduce 的期望 key。
  2. 自动比对 `compute_report_context()` 输出 key 与 `html-report-template.html` 中的 `{{ }}` 变量列表。
- **测试方法**：CI 中跑此测试，任何契约不一致即失败。

---

## 修复优先级与依赖关系

```
A1 (数据契约) ──┬── B* (OCR 修复，可并行)
               ├── C1, C2 (Shuffle 字段修正，依赖 A1)
               ├── C3-C9 (MapReduce 其余修复，依赖 C1, C2)
               └── A2 ── D1 (HTML Context 函数，依赖 A2)
                         D2 (模板通用化)
                         D3 (管道集成，依赖 D1, D2)

E1, E2 (集成测试，依赖以上全部)
```

**建议执行顺序：** A1 → C1/C2 → C3–C9 → A2 → D1 → D2 → D3 → B* → E1/E2

---

## 文件变更清单

| 文件 | 操作 | 任务 |
|------|------|------|
| `dev/docs/data-contract.md` | 新建 | A1 |
| `dev/docs/template-context.md` | 新建 | A2 |
| `dev/docs/fix-plan.md` | 新建 | 本文档 |
| `scripts/ocr_siliconflow.py` | 修改 | B1, B3 |
| `scripts/extract_mineru.py` | 修改 | B2 |
| `scripts/v2/map_extract.py` | 修改 | A1 |
| `scripts/v2/shuffle_group.py` | 修改 | C1, C2 |
| `scripts/v2/reduce_merge.py` | 修改 | C3 |
| `scripts/v2/llm_client.py` | 修改 | C4, C8 |
| `scripts/v2/pipeline_v2.py` | 修改 | C5, C6, C7, C9, D3 |
| `scripts/v2/render_html.py` | 新建 | D1 |
| `references/html-report-template.html` | 修改 | D2 |
| `requirements.txt` | 修改 | D3 |
| `tests/v2/test_shuffle_group.py` | 新建 | C1, C2 |
| `tests/v2/test_data_contract.py` | 新建 | E2 |
| `tests/v2/test_e2e.py` | 修改/新建 | E1 |
