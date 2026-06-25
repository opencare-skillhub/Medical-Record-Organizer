保留了的 v1 文件（仍被 v2 或共享代码引用）：

scripts/render_html.py — v2 借用 _generate_multi_marker_svg 等 3 个图表函数
scripts/llm_client.py — mdt_analysis / reduce_merge / map_extract 依赖
scripts/classify.py / scripts/manifest.py / scripts/security.py — manifest 链路
scripts/critical_values.py / scripts/parse_genetics.py — 渲染层依赖
scripts/ingest.py / scripts/route_ocr.py / scripts/asr_stepfun.py / scripts/ocr_runner.py / scripts/memory.py — 前端链路共享
