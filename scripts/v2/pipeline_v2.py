"""
v2 端到端流水线

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

# 确保项目根在 sys.path 中（支持直接 python scripts/v2/pipeline_v2.py 运行）
_ProjectRoot = Path(__file__).resolve().parent.parent.parent
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

from scripts.v2.desensitize import desensitize_directory
from scripts.v2.map_extract import extract_batch
from scripts.v2.reduce_merge import reduce_lab_trends, reduce_imaging_narrative, reduce_medication_history
from scripts.mdt_analysis import run_mdt_analysis
from scripts.v2.shuffle_group import group_by_type, merge_lab_trends

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


# 需要 OCR 预处理的原始文件扩展名（对齐 route_ocr.RAW_OCR_EXTENSIONS）
# 文本/数据类文件（.md/.txt/.json/.csv）不送 OCR，直接进 v2 流程
_NON_OCR_EXTENSIONS = {'.md', '.txt', '.json', '.csv'}


def _preprocess_raw_files(input_path: Path, output_path: Path, *, skip_ocr: bool = False) -> Path:
    """检测原始图片/PDF，做 OCR 预处理 → 写入 output/extracted/*.md，返回 md 输入目录。

    若无原始文件直接返回 input_path；skip_ocr 或 OCR 失败也写入空 md 不中断。
    """
    raw_files = [
        f for f in input_path.iterdir()
        if f.is_file()
        and f.suffix.lower() not in _NON_OCR_EXTENSIONS
        and not f.name.startswith('.')
    ]

    if not raw_files:
        return input_path

    logger.info("检测到 %d 个原始文件，开始 OCR 预处理", len(raw_files))
    extract_dir = output_path / 'extracted'
    extract_dir.mkdir(parents=True, exist_ok=True)

    # 已有的 .md/.txt 等文本文件直接软链/复制到 extract_dir，统一输入目录
    import shutil
    for f in input_path.iterdir():
        if f.is_file() and f.suffix.lower() in _NON_OCR_EXTENSIONS and not f.name.startswith('.'):
            dst = extract_dir / f.name
            if not dst.exists():
                try:
                    shutil.copy2(f, dst)
                except Exception:
                    dst.write_text(f.read_text(encoding='utf-8'), encoding='utf-8')

    if skip_ocr:
        for raw_file in raw_files:
            (extract_dir / f"{raw_file.stem}.md").write_text('', encoding='utf-8')
        return extract_dir

    from scripts.route_ocr import extract_text

    for raw_file in raw_files:
        logger.info("处理原始文件: %s", raw_file.name)
        md_path = extract_dir / f"{raw_file.stem}.md"
        try:
            text = extract_text(raw_file, extract_dir=extract_dir)
            md_path.write_text(text if text else '', encoding='utf-8')
            logger.info("OCR 完成: %s -> %s (%d 字符)", raw_file.name, md_path.name, len(text or ''))
        except Exception as exc:
            logger.warning("OCR 失败 %s: %s", raw_file.name, exc)
            md_path.write_text('', encoding='utf-8')

    return extract_dir


def run_pipeline(
    input_dir: str,
    output_dir: str,
    *,
    patient_id: str = 'P_report_mess',
    model: Optional[str] = None,
    skip_ocr: bool = False,
    formats: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """执行 v2 MapReduce 流水线。

    支持原始图片/PDF 输入（自动 OCR 预处理 → extracted/*.md）；
    也支持直接 .md 输入。skip_ocr=True 跳过 OCR（仅处理 .md）。

    formats: 输出格式列表，['html', 'md', 'docx', 'xlsx'] 的子集，
             None（默认）表示生成所有格式。
    """
    input_path = Path(input_dir).resolve()  # C7: resolve 入参
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Phase 0: 原始文件 OCR 预处理（若有）
    md_input_dir = _preprocess_raw_files(input_path, output_path, skip_ocr=skip_ocr)

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

    # MDT 结果单独落盘（HTML/MD/DOCX 渲染层与未来导出均可复用）
    try:
        (output_path / 'mdt_analysis.json').write_text(
            json.dumps(mdt_analysis, ensure_ascii=False, indent=2), encoding='utf-8'
        )
    except Exception as exc:
        logger.warning('mdt_analysis.json 落盘失败：%s', exc)

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
    _render_reports(profile, groups, output_path, formats=formats)

    logger.info(
        'v2 流水线完成: patient=%s files=%d groups=%s',
        patient_id,
        len(extracted),
        ','.join(f'{k}={len(v)}' for k, v in groups.items()),
    )
    return profile


def _render_reports(
    profile: Dict[str, Any],
    groups: Dict[str, List[Dict[str, Any]]],
    output_path: Path,
    formats: List[str] | None = None,
) -> None:
    """生成 HTML / Markdown / DOCX / XLSX 报告。

    formats: ['html', 'md', 'docx', 'xlsx'] 的子集，None 表示生成所有。
    """
    from scripts.v2.render_html import render_html_report
    from scripts.render_md import render_md

    if formats is None or 'html' in formats:
        html_path = render_html_report(profile, groups, output_path)
        if html_path:
            logger.info('HTML 报告已生成: %s', html_path)
        else:
            logger.warning('HTML 报告渲染失败')

    if formats is None or 'md' in formats:
        try:
            md_path = render_md(profile, groups=groups, output_path=output_path / 'case_report.md')
            logger.info('Markdown 报告已生成: %s', md_path)
        except Exception as exc:
            logger.warning('Markdown 报告渲染失败: %s', exc)

    if formats is None or 'docx' in formats:
        try:
            from scripts.v2.render_docx import render_docx_report
            docx_path = render_docx_report(profile, groups, output_path)
            if docx_path:
                logger.info('DOCX 报告已生成: %s', docx_path)
        except Exception as exc:
            logger.warning('DOCX 报告渲染失败: %s', exc)

    if formats is None or 'xlsx' in formats:
        try:
            from scripts.v2.render_xlsx import render_xlsx_report
            xlsx_path = render_xlsx_report(profile, groups, output_path)
            if xlsx_path:
                logger.info('XLSX 报告已生成: %s', xlsx_path)
        except Exception as exc:
            logger.warning('XLSX 报告渲染失败: %s', exc)


def _render_markdown(profile: Dict[str, Any], groups: Dict[str, List[Dict[str, Any]]], output_path: Path) -> None:
    """生成 Markdown 报告。"""
    lines: List[str] = []
    lines.append('# 病案整理报告')
    lines.append('')
    lines.append(f'- 患者ID：{profile.get("patient_id", "")}')
    lines.append(f'- 生成时间：{profile.get("generated_at", "")}')
    lines.append(f'- 处理文件数：{profile.get("file_count", 0)}')
    lines.append('')

    lines.append('## 分类摘要')
    lines.append('')
    for group, count in sorted((profile.get('groups') or {}).items()):
        lines.append(f'- {group}: {count}')
    lines.append('')

    lab_trends = profile.get('lab_trends') or {}
    if lab_trends:
        lines.append('## 检验指标趋势')
        lines.append('')
        for indicator, data in sorted(lab_trends.items()):
            lines.append(f'### {indicator}')
            trend = data.get('trend') or []
            if trend:
                lines.append('| 日期 | 数值 | 单位 |')
                lines.append('|------|------|------|')
                for item in trend:
                    lines.append(f'| {item.get("date", "")} | {item.get("value", "")} | {item.get("unit", "")} |')
            lines.append('')

    med_tl = profile.get('medication_timeline') or {}
    if med_tl.get('timeline'):
        lines.append('## 用药时间线')
        lines.append('')
        for med in med_tl['timeline']:
            lines.append(f'- {med.get("name", "")}: {med.get("dosage") or med.get("dose", "")} ({med.get("start_date", "")})')
        lines.append('')

    lines.append('## 免责声明')
    lines.append('')
    lines.append('本病例档案仅为医疗资料整理与结构化归档，不构成任何诊断或治疗建议。')
    lines.append('')

    output_path.write_text('\n'.join(lines), encoding='utf-8')


def _parse_format(format_arg: str) -> List[str]:
    """把 --format 字符串解析为格式列表。"""
    if format_arg == 'all':
        return ['html', 'md', 'docx', 'xlsx']
    # 别名映射
    alias = {'doc': 'docx', 'xls': 'xlsx'}
    return [alias.get(f, f) for f in format_arg.split(',')]


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    """命令行入口。"""
    import argparse
    
    parser = argparse.ArgumentParser(description='v2 病案整理流水线')
    parser.add_argument('--input-dir', required=True, help='输入目录（.md 文件 或 原始图片/PDF）')
    parser.add_argument('--output-dir', required=True, help='输出目录')
    parser.add_argument('--patient-id', default='P_report_mess', help='患者ID')
    parser.add_argument('--model', help='LLM 模型名称')
    parser.add_argument('--format', choices=['html', 'md', 'docx', 'xlsx', 'doc', 'xls', 'all'],
                        default='all', help='输出格式（doc/xls 是 docx/xlsx 的别名）')
    parser.add_argument('--skip-ocr', action='store_true', help='跳过 OCR 预处理（仅处理 .md 文件）')
    parser.add_argument('--open', action='store_true', help='生成后自动打开 HTML')
    parser.add_argument('--log-level', default='INFO', help='日志级别')
    args = parser.parse_args(argv)

    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO))

    input_path = Path(args.input_dir)
    if not input_path.exists() or not input_path.is_dir():
        print(f"❌ 输入目录不存在: {input_path}")
        return 1

    print(f"📋 开始运行 v2 流水线...")
    print(f"   输入目录: {input_path}")
    print(f"   输出目录: {args.output_dir}")
    print(f"   患者ID: {args.patient_id}")
    print(f"   输出格式: {args.format}")
    print("=" * 60)

    try:
        profile = run_pipeline(
            input_dir=str(input_path),
            output_dir=args.output_dir,
            patient_id=args.patient_id,
            model=args.model,
            skip_ocr=args.skip_ocr,
            formats=_parse_format(args.format),
        )
        
        print("\n" + "=" * 60)
        print("✅ v2 流水线运行完毕！")
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
