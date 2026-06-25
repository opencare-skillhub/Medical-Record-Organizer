"""
端到端病案整理流水线

流程：
  原始 .md -> 脱敏 -> Map LLM -> Shuffle -> Reduce LLM -> Profile -> 报告
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# 确保项目根在 sys.path 中（支持直接 python scripts/pipeline.py 运行）
_ProjectRoot = Path(__file__).resolve().parent.parent
if str(_ProjectRoot) not in sys.path:
    sys.path.insert(0, str(_ProjectRoot))

# 自动加载 .env（如果存在）
_dotenv_path = _ProjectRoot / ".env"
if _dotenv_path.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(str(_dotenv_path), override=True)
    except ImportError:
        pass  # python-dotenv 未安装时静默跳过

logger = logging.getLogger(__name__)

from scripts.desensitize import desensitize_directory
from scripts.map_extract import extract_batch
from scripts.reduce_merge import reduce_lab_trends, reduce_imaging_narrative, reduce_medication_history
from scripts.shuffle_group import group_by_type, merge_lab_trends
from scripts.mdt_analysis import run_mdt_analysis

try:
    from jinja2 import Environment, FileSystemLoader, Template
    _JINJA2_AVAILABLE = True
except ImportError:
    _JINJA2_AVAILABLE = False


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _file_key(file_path: Path) -> str:
    """统一用 resolve() 后的路径作为增量比对的 key（C7）。"""
    return str(Path(file_path).resolve())


def _load_existing_mappings(mappings_path: Path) -> Dict[str, Any]:
    """从 mappings.json 恢复已有映射（C6 增量合并）。"""
    if not mappings_path.exists():
        return {}
    try:
        return json.loads(mappings_path.read_text(encoding='utf-8'))
    except Exception:
        return {}


def _persist_mappings(
    mappings: Dict[str, Any],
    mappings_path: Path,
    existing: Dict[str, Any],
) -> None:
    """增量合并并持久化脱敏映射（C6）。"""
    merged = dict(existing)
    merged.update(mappings)
    mappings_path.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2), encoding='utf-8'
    )


def run_pipeline(
    input_dir: str,
    output_dir: str,
    *,
    patient_id: str = 'P_report_mess',
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """执行 MapReduce 流水线。支持原始图片/PDF 输入（自动 OCR 预处理）。"""
    input_path = Path(input_dir).resolve()  # C7: resolve 入参
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # 检测输入目录是否包含原始文件（非 .md）
    raw_files = [
        f for f in input_path.iterdir()
        if f.is_file() and f.suffix.lower() not in {'.md', '.json', '.txt', '.csv'}
        and not f.name.startswith('.')
    ]

    if raw_files:
        # OCR 预处理：原始文件 → .md
        logger.info("检测到 %d 个原始文件，开始 OCR 预处理", len(raw_files))
        extract_dir = output_path / 'extracted'
        extract_dir.mkdir(exist_ok=True)

        from scripts.route_ocr import extract_text

        for raw_file in raw_files:
            logger.info("处理原始文件: %s", raw_file.name)
            try:
                text = extract_text(raw_file, extract_dir=extract_dir)
                md_path = extract_dir / f"{raw_file.stem}.md"
                md_path.write_text(text, encoding='utf-8')
                logger.info("OCR 完成: %s -> %s (%d 字符)", raw_file.name, md_path.name, len(text))
            except Exception as exc:
                logger.warning("OCR 失败 %s: %s", raw_file.name, exc)
                (extract_dir / f"{raw_file.stem}.md").write_text("", encoding='utf-8')

        md_input_dir = extract_dir
    else:
        md_input_dir = input_path

    md_files = sorted(md_input_dir.glob('*.md'))
    if not md_files:
        return {'patient_id': patient_id, 'status': 'no_input', 'files': 0}

    # Phase 1: 脱敏
    sanitized_dir = output_path / 'sanitized'
    mappings_path = output_path / 'mappings.json'
    existing_mappings = _load_existing_mappings(mappings_path)  # C6: 恢复映射
    mappings = desensitize_directory(str(md_input_dir), str(sanitized_dir))
    _persist_mappings(mappings, mappings_path, existing_mappings)  # C6: 持久化

    # Phase 2: Map
    map_dir = output_path / 'map'
    extracted = extract_batch(str(sanitized_dir), str(map_dir), model=model)

    # Phase 3: Shuffle
    groups = group_by_type(extracted)
    lab_trends = merge_lab_trends(groups.get('lab', []))

    # Phase 4: Reduce
    lab_analysis = reduce_lab_trends(lab_trends, model=model)
    med_timeline = reduce_medication_history(groups.get('medication', []), model=model)
    imaging_narrative = reduce_imaging_narrative(groups.get('imaging', []), model=model)

    # Phase 4.5: MDT 多学科分析
    mdt_analysis = run_mdt_analysis(
        {
            'demographics': {},
            'lab_trends': lab_trends,
            'lab_analysis': lab_analysis,
            'medication_timeline': med_timeline,
            'imaging_narrative': imaging_narrative,
            'gaps': [],
            'timeline': [],
        },
        groups,
        model=model,
    )

    # Phase 5: Profile 组装
    profile: Dict[str, Any] = {
        'patient_id': patient_id,
        'generated_at': _now_iso(),
        'input_dir': str(input_path),
        'file_count': len(md_files),
        'map_count': len(extracted),
        'groups': {k: len(v) for k, v in groups.items()},
        'lab_trends': lab_trends,
        'lab_analysis': lab_analysis,
        'medication_timeline': med_timeline,
        'imaging_narrative': imaging_narrative,
        'mdt_analysis': mdt_analysis,
        'mappings_path': str(mappings_path),
        'output_dir': str(output_path),
    }

    (output_path / 'profile.json').write_text(
        json.dumps(profile, ensure_ascii=False, indent=2), encoding='utf-8'
    )

    # Phase 6: 渲染报告
    _render_reports(profile, groups, output_path)

    logger.info(
        '流水线完成: patient=%s files=%d groups=%s',
        patient_id,
        len(extracted),
        ','.join(f'{k}={len(v)}' for k, v in groups.items()),
    )
    return profile


def _render_reports(
    profile: Dict[str, Any],
    groups: Dict[str, List[Dict[str, Any]]],
    output_path: Path,
) -> None:
    """生成 HTML（委托 render_html.py）+ Markdown 报告（委托 render_md.py）。"""
    from scripts.render_html import render_html_report
    from scripts.render_md import render_md
from scripts.mdt_analysis import run_mdt_analysis

    # HTML 报告（核心输出）
    html_path = render_html_report(profile, groups, output_path)
    if html_path:
        logger.info('HTML 报告已生成: %s', html_path)
    else:
        logger.warning('HTML 报告渲染失败（render_html_report 返回 None）')

    # Markdown 报告（委托 render_md.py，使用 case-report-template.md）
    try:
        md_path = render_md(profile, groups=groups, output_path=output_path / 'case_report.md')
        logger.info('Markdown 报告已生成: %s', md_path)
    except Exception as exc:
        logger.warning('Markdown 报告渲染失败: %s', exc)


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    """命令行入口。"""
    import argparse
    
    parser = argparse.ArgumentParser(description='病案整理流水线')
    parser.add_argument('--input-dir', required=True, help='输入目录（.md 文件 或 原始图片/PDF）')
    parser.add_argument('--output-dir', required=True, help='输出目录')
    parser.add_argument('--patient-id', default='P_report_mess', help='患者ID')
    parser.add_argument('--model', help='LLM 模型名称')
    parser.add_argument('--format', choices=['html', 'md', 'all'], default='all', help='输出格式')
    parser.add_argument('--open', action='store_true', help='生成后自动打开 HTML')
    parser.add_argument('--log-level', default='INFO', help='日志级别')
    parser.add_argument('--skip-ocr', action='store_true', help='跳过 OCR 预处理（仅处理 .md 文件）')
    args = parser.parse_args(argv)
    
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO))
    
    input_path = Path(args.input_dir)
    if not input_path.exists() or not input_path.is_dir():
        print(f"❌ 输入目录不存在: {input_path}")
        return 1
    
    print(f"📋 开始运行 流水线...")
    print(f"   输入目录: {input_path}")
    print(f"   输出目录: {args.output_dir}")
    print(f"   患者ID: {args.patient_id}")
    print(f"   输出格式: {args.format}")
    print("=" * 60)
    
    # 如果输入目录包含原始文件（非 .md），先做 OCR 预处理
    md_files = list(input_path.glob('*.md'))
    raw_files = [
        f for f in input_path.iterdir()
        if f.is_file() and f.suffix.lower() not in {'.md', '.json', '.txt', '.csv'}
        and not f.name.startswith('.')
    ]
    
    if raw_files and not args.skip_ocr:
        print(f"\n🔍 检测到 {len(raw_files)} 个原始文件，开始 OCR 预处理...")
        extract_dir = input_path / 'extracted'
        extract_dir.mkdir(exist_ok=True)
        
        from scripts.route_ocr import extract_text
        
        for raw_file in raw_files:
            print(f"   处理: {raw_file.name}")
            try:
                text = extract_text(raw_file, extract_dir=extract_dir)
                md_path = extract_dir / f"{raw_file.stem}.md"
                md_path.write_text(text, encoding='utf-8')
                print(f"   ✅ -> {md_path.name} ({len(text)} 字符)")
            except Exception as exc:
                print(f"   ❌ 失败: {exc}")
                # 创建空文件避免 pipeline 报错
                (extract_dir / f"{raw_file.stem}.md").write_text("", encoding="utf-8")
        
        md_files = list(extract_dir.glob('*.md'))
        print(f"\n✅ OCR 预处理完成，共 {len(md_files)} 个 .md 文件")
        
        if not md_files:
            print("❌ 没有可处理的 .md 文件")
            return 1
    elif not md_files:
        print("❌ 输入目录中没有 .md 文件，且 --skip-ocr 已设置")
        return 1
    
    # 使用 .md 文件目录作为输入
    actual_input = input_path if not raw_files or args.skip_ocr else (input_path / 'extracted')
    
    try:
        profile = run_pipeline(
            input_dir=str(actual_input),
            output_dir=args.output_dir,
            patient_id=args.patient_id,
            model=args.model,
        )
        
        print("\n" + "=" * 60)
        print("✅ 流水线运行完毕！")
        print(f"   患者ID: {profile.get('patient_id')}")
        print(f"   处理文件数: {profile.get('file_count', 0)}")
        print(f"   分类: {profile.get('groups', {})}")
        
        # 打开 HTML
        if args.format in ('html', 'all') and args.open:
            output_path = Path(args.output_dir)
            html_file = output_path / 'report.html'
            if not html_file.exists():
                html_file = output_path / 'case_report.html'
            if html_file.exists():
                import webbrowser
                webbrowser.open(f"file://{html_file}")
                print(f"🌐 已打开报告: {html_file}")
        
        return 0
        
    except Exception as exc:
        print(f"\n❌ 流水线运行失败: {exc}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
