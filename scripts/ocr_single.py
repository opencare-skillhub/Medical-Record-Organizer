#!/usr/bin/env python3
"""
单文件 OCR 提取脚本

用于快速提取单张图片/单个 PDF 的文字内容。支持多种引擎选择，
无需启动完整流水线。

使用方法:
  python3 scripts/ocr_single.py input.jpg
  python3 scripts/ocr_single.py input.pdf -o output.md
  python3 scripts/ocr_single.py input.png --engine deepseek
  python3 scripts/ocr_single.py input.pdf --engine mineru --retries 5
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

# 确保项目根目录在 sys.path 中
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(
        description='单文件 OCR 提取（图片/PDF → 文本）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
引擎选项:
  auto      自动选择（图像/扫描PDF→MinerU，文字PDF→PyMuPDF）
  mineru    MinerU API（图片/扫描PDF首选，带重试）
  deepseek  SiliconFlow DeepSeek-OCR（速度快，适合图片）
  pymupdf   PyMuPDF 本地提取（仅PDF，零 API 调用）
  batch     MinerU 批量模式（大PDF>10页适用）

回退链: MinerU → DeepSeek-OCR → PyMuPDF(仅PDF)
如指定 --engine 则固定使用该引擎，不回退。

示例:
  %(prog)s report.jpg                      # 自动引擎，输出 report.md
  %(prog)s scan.pdf -o result.md --engine deepseek
  %(prog)s gene.pdf --engine batch -o gene.md
        ''',
    )
    parser.add_argument('input', type=str, help='输入文件路径（图片/PDF/HTML）')
    parser.add_argument('-o', '--output', type=str, default=None,
                        help='输出 .md 路径（默认：同目录下同名 .md）')
    parser.add_argument('--engine', type=str, default='auto',
                        choices=['auto', 'mineru', 'deepseek', 'pymupdf', 'batch'],
                        help='提取引擎（默认: auto）')
    parser.add_argument('--retries', type=int, default=3,
                        help='mineru 模式重试次数（默认: 3）')
    parser.add_argument('--cache-dir', type=str, default=None,
                        help='缓存目录（默认: 同目录 .ocr_cache/）')
    parser.add_argument('--log-level', type=str, default='INFO',
                        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'])

    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format='%(levelname)s:%(name)s:%(message)s',
    )

    input_path = Path(args.input).resolve()
    if not input_path.exists():
        print(f'❌ 文件不存在: {input_path}', file=sys.stderr)
        sys.exit(1)

    if args.output:
        output_path = Path(args.output).resolve()
    else:
        output_path = input_path.with_suffix('.md')

    # 缓存目录
    if args.cache_dir:
        cache_dir = Path(args.cache_dir)
    else:
        cache_dir = input_path.parent / '.ocr_cache'
    cache_dir.mkdir(parents=True, exist_ok=True)

    start = time.time()
    text = ''

    # ---- ENGINE DISPATCH ----
    if args.engine == 'auto':
        text = _extract_auto(input_path, cache_dir)
    elif args.engine == 'mineru':
        text = _extract_mineru(input_path, cache_dir, max_retries=args.retries)
    elif args.engine == 'deepseek':
        text = _extract_deepseek(input_path, cache_dir)
    elif args.engine == 'pymupdf':
        text = _extract_pymupdf(input_path)
    elif args.engine == 'batch':
        text = _extract_mineru_batch_single(input_path, cache_dir)

    elapsed = time.time() - start

    # 写入输出
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(text if text else '', encoding='utf-8')

    # 结果摘要
    fail = text.startswith('[') if text else True
    char_count = len(text or '')
    lines = (text or '').count('\n') + 1

    if fail:
        print(f'❌ OCR 失败 ({args.engine}, {elapsed:.1f}s)')
        if text:
            print(f'   错误: {text}')
        sys.exit(1)
    else:
        print(f'✅ OCR 成功 ({args.engine}, {elapsed:.1f}s)')
        print(f'   输入: {input_path.name}')
        print(f'   输出: {output_path}')
        print(f'   字符: {char_count:,} 字符, {lines} 行')
        sys.exit(0)


# ---------------------------------------------------------------------------
# 内部：各引擎提取
# ---------------------------------------------------------------------------

def _extract_auto(file_path: Path, cache_dir: Path) -> str:
    """自动路由：借用 route_ocr 引擎选择，调用最优引擎。"""
    from scripts.route_ocr import route_ocr, extract_text
    try:
        return extract_text(file_path, extract_dir=cache_dir)
    except Exception as e:
        logger.warning("Auto extract 失败: %s", e)
        return f'[Auto提取失败: {e}]'


def _extract_mineru(file_path: Path, cache_dir: Path, max_retries: int = 3) -> str:
    """单文件 MinerU（带重试）。失败后尝试 DeepSeek OCR 托底。"""
    from scripts.route_ocr import extract_via_mineru, _is_fail_marker
    try:
        text = extract_via_mineru(file_path, extract_dir=cache_dir, max_retries=max_retries)
        if not _is_fail_marker(text):
            return text
        logger.info("MinerU 失败，回退到 DeepSeek OCR: %s", file_path.name)
        return _extract_deepseek(file_path, cache_dir)
    except Exception as e:
        logger.warning("MinerU 异常: %s", e)
        return f'[MinerU异常: {e}]'


def _extract_mineru_batch_single(file_path: Path, cache_dir: Path) -> str:
    """用批量 API 处理单文件（适合大 PDF）。"""
    from scripts.route_ocr import extract_via_mineru_batch, _is_fail_marker
    try:
        results = extract_via_mineru_batch([file_path], extract_dir=cache_dir)
        text = results.get(file_path, '')
        if not text:
            return '[Batch提取失败: 无结果]'
        if not _is_fail_marker(text):
            return text
        logger.info("Batch 失败，回退到 DeepSeek OCR: %s", file_path.name)
        return _extract_deepseek(file_path, cache_dir)
    except Exception as e:
        logger.warning("Batch 异常: %s", e)
        return f'[Batch异常: {e}]'


def _extract_deepseek(file_path: Path, cache_dir: Path) -> str:
    """DeepSeek OCR（图片/PDF转文字）。失败后尝试 PyMuPDF 托底。"""
    from scripts.route_ocr import ocr_via_siliconflow, _is_fail_marker
    try:
        text = ocr_via_siliconflow(file_path, extract_dir=cache_dir)
        if _is_fail_marker(text) and file_path.suffix.lower() == '.pdf':
            logger.info("DeepSeek OCR 失败，回退到 PyMuPDF: %s", file_path.name)
            pymupdf_text = _extract_pymupdf(file_path)
            if pymupdf_text and not pymupdf_text.startswith('['):
                return pymupdf_text
        return text
    except Exception as e:
        logger.warning("DeepSeek OCR 异常: %s", e)
        if file_path.suffix.lower() == '.pdf':
            return _extract_pymupdf(file_path)
        return f'[DeepSeekOCR异常: {e}]'


def _extract_pymupdf(file_path: Path) -> str:
    """PyMuPDF 本地 PDF 文字提取（零 API 调用）。"""
    if file_path.suffix.lower() != '.pdf':
        return '[PyMuPDF仅支持PDF]'
    try:
        from scripts.route_ocr import _extract_pdf_text
        text = _extract_pdf_text(file_path)
        if text:
            return text
        return '[PyMuPDF提取为空]'
    except Exception as e:
        return f'[PyMuPDF异常: {e}]'


if __name__ == '__main__':
    main()
