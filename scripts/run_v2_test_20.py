#!/usr/bin/env python3
"""
v2 真实端到端测试脚本：
1. 从 /Users/qinxiaoqiang/Downloads/report_mess/data/extracted 随机选 20 个已OCR的 .md 文件
2. 调用 scripts/v2/pipeline_v2.py 跑完整 MapReduce 链路
3. 检查生成的 raw data JSON 质量
4. 基于 v2 数据渲染 HTML 报告
"""
import json
import random
import shutil
import sys
import webbrowser
from pathlib import Path

# 路径
source_dir = Path("/Users/qinxiaoqiang/Downloads/report_mess/data/extracted")
test_inputs = Path("/Users/qinxiaoqiang/Downloads/patient-record-organizer/temp_test_inputs_v2")
project_root = Path("/Users/qinxiaoqiang/Downloads/patient-record-organizer")
v2_output = project_root / "temp_v2_output"

# 1. 收集已OCR的 .md 文件
all_files = sorted(source_dir.glob("*.md"))
print(f"📂 已OCR的 .md 文件共 {len(all_files)} 个")

if len(all_files) == 0:
    print("❌ 错误：data/extracted/ 中没有 .md 文件！")
    sys.exit(1)

# 2. 随机选 20 个
selected = random.sample(all_files, min(20, len(all_files)))
print(f"🎲 随机选择 {len(selected)} 个文件：")
for i, f in enumerate(selected, 1):
    print(f"   [{i}] {f.relative_to(source_dir)}")

# 3. 准备目录
if test_inputs.exists():
    shutil.rmtree(test_inputs)
test_inputs.mkdir(parents=True, exist_ok=True)

if v2_output.exists():
    shutil.rmtree(v2_output)
v2_output.mkdir(parents=True, exist_ok=True)

# 4. 拷贝文件
for f in selected:
    dest = test_inputs / f.name
    counter = 1
    while dest.exists():
        dest = test_inputs / f"{f.stem}_{counter}{f.suffix}"
        counter += 1
    shutil.copy2(f, dest)

print(f"\n🚀 文件已拷贝到: {test_inputs}")

# 5. 调用 v2 pipeline
sys.path.insert(0, str(project_root))
from scripts.v2.pipeline_v2 import run_pipeline

patient_id = "P_v2_real_test_20"
print(f"\n📋 开始运行 v2 完整流程...")
print(f"   患者ID: {patient_id}")
print("=" * 60)

try:
    profile = run_pipeline(
        input_dir=str(test_inputs),
        output_dir=str(v2_output),
        patient_id=patient_id,
    )

    print("\n" + "=" * 60)
    print("✅ v2 流水线运行完毕！")

    # 检查输出
    map_dir = v2_output / "map"
    profile_path = v2_output / "profile.json"
    report_path = v2_output / "case_report.md"

    print(f"\n📊 输出检查：")
    print(f"   profile.json: {'✅ 存在' if profile_path.exists() else '❌ 缺失'}")
    print(f"   case_report.md: {'✅ 存在' if report_path.exists() else '❌ 缺失'}")

    if map_dir.exists():
        json_files = list(map_dir.glob("*.json"))
        print(f"   raw data JSON: {len(json_files)} 个文件")
        for jf in sorted(json_files)[:5]:
            try:
                data = json.loads(jf.read_text(encoding="utf-8"))
                rt = data.get("report_type", "unknown")
                conf = data.get("confidence", 0)
                lv = len(data.get("lab_values", []))
                meds = len(data.get("medications", []))
                findings = len(data.get("findings", []))
                print(f"      {jf.name}: type={rt}, conf={conf:.2f}, lab={lv}, meds={meds}, findings={findings}")
            except Exception as e:
                print(f"      {jf.name}: ❌ 解析失败: {e}")
    else:
        print("   raw data JSON: ❌ map/ 目录不存在")

    # 显示 profile 摘要
    if profile_path.exists():
        import json
        p = json.loads(profile_path.read_text(encoding="utf-8"))
        print(f"\n📋 Profile 摘要：")
        print(f"   patient_id: {p.get('patient_id')}")
        print(f"   file_count: {p.get('file_count')}")
        print(f"   map_count: {p.get('map_count')}")
        print(f"   groups: {p.get('groups', {})}")

    # 显示报告前几行
    if report_path.exists():
        print(f"\n📄 报告前 30 行：")
        lines = report_path.read_text(encoding="utf-8").splitlines()
        for line in lines[:30]:
            print(f"   {line}")

except Exception as exc:
    print(f"\n❌ 异常: {exc}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
