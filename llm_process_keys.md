原始 .md (110份)
    │
    ▼ ① 脱敏层（本地、无 LLM）
    │  正则替换：姓名→[NAME]、身份证→[ID]、电话→[PHONE]、病历号→[MRN]
    │  产出：sanitized/*.md（可安全送 LLM）
    │
    ▼ ② Map 层（每文件独立 LLM，小上下文、专注、不丢细节）
    │  每份文件单独喂 LLM，用 function calling 强制输出结构化 JSON：
    │  {report_type, date, diagnosis[], lab_values[], medications[], findings...}
    │  每文件一个 extracted/*.json
    │
    ▼ ③ Shuffle（本地、无 LLM）
    │  按 report_type 分类 + 按 date 排序 + 按 indicator 合并趋势
    │
    ▼ ④ Reduce 层（LLM 做跨文档推理）
    │  把同类文档的 JSON 聚合后喂 LLM：
    │  - 检验组：13 次 CA199 → LLM 判断趋势、是否连续上升、与影像是否一致
    │  - 用药组：所有处方 → LLM 重建完整化疗周期时间线
    │  - 影像组：所有 CT → LLM 提取"病灶变化"连贯叙事
    │
    ▼ ⑤ Profile 组装 + 渲染
