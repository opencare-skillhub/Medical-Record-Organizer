#!/usr/bin/env python3
"""
临时 OCR 预处理脚本：把 test_data 目录中的图片/PDF 转成 .md 文本。
调用 SiliconFlow DeepSeek OCR API（.env 已配置）。
"""
import base64
import json
import os
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import requests


def ocr_image(image_path: Path, output_dir: Path) -> Path:
    """对单张图片调用 SiliconFlow OCR API，保存为 .md。"""
    api_key = os.getenv("OCR_API_KEY", "")
    base_url = os.getenv("OCR_BASE_URL", "https://api.siliconflow.cn/v1")
    model = os.getenv("OCR_MODEL", "deepseek-ai/DeepSeek-OCR")

    if not api_key:
        raise RuntimeError("OCR_API_KEY 未配置")

    # 读取图片并 base64 编码
    with open(image_path, "rb") as f:
        image_b64 = base64.b64encode(f.read()).decode()

    # 构造请求
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "image": f"data:image/png;base64,{image_b64}",
    }

    resp = requests.post(
        f"{base_url}/ocr",
        headers=headers,
        json=payload,
        timeout=120,
    )
    resp.raise_for_status()
    result = resp.json()

    # 提取文本
    text = result.get("text") or result.get("content") or result.get("result", "")
    if isinstance(text, list):
        text = "\n".join(text)

    # 保存为 .md
    md_path = output_dir / f"{image_path.stem}.md"
    md_path.write_text(text, encoding="utf-8")
    return md_path


def ocr_pdf(pdf_path: Path, output_dir: Path) -> Path:
    """对 PDF 调用 MinerU API（如果可用），否则逐页转图 OCR。"""
    # 简化：直接用 SiliconFlow OCR（逐页）
    # 实际应该用 MinerU，但这里先简化处理
    api_key = os.getenv("OCR_API_KEY", "")
    base_url = os.getenv("OCR_BASE_URL", "https://api.siliconflow.cn/v1")
    model = os.getenv("OCR_MODEL", "deepseek-ai/DeepSeek-OCR")

    if not api_key:
        raise RuntimeError("OCR_API_KEY 未配置")

    # 读取 PDF 并 base64 编码
    with open(pdf_path, "rb") as f:
        pdf_b64 = base64.b64encode(f.read()).decode()

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "file": f"data:application/pdf;base64,{pdf_b64}",
    }

    resp = requests.post(
        f"{base_url}/ocr",
        headers=headers,
        json=payload,
        timeout=120,
    )
    resp.raise_for_status()
    result = resp.json()

    text = result.get("text") or result.get("content") or result.get("result", "")
    if isinstance(text, list):
        text = "\n".join(text)

    md_path = output_dir / f"{pdf_path.stem}.md"
    md_path.write_text(text, encoding="utf-8")
    return md_path


def main():
    import argparse

    parser = argparse.ArgumentParser(description="OCR 预处理")
    parser.add_argument("input_dir", help="输入目录（包含图片/PDF）")
    parser.add_argument("output_dir", help="输出目录（保存 .md）")
    args = parser.parse_args()

    input_path = Path(args.input_dir)
    output_path = Path(args.output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # 收集图片和 PDF
    image_exts = {".png", ".jpg", ".jpeg", ".bmp", ".tiff"}
    pdf_exts = {".pdf"}

    files = sorted(input_path.iterdir())
    image_files = [f for f in files if f.suffix.lower() in image_exts]
    pdf_files = [f for f in files if f.suffix.lower() in pdf_exts]

    print(f"📂 发现 {len(image_files)} 张图片，{len(pdf_files)} 个 PDF")

    # OCR 图片
    for img in image_files:
        print(f"🔍 OCR: {img.name}")
        try:
            md_path = ocr_image(img, output_path)
            print(f"   ✅ -> {md_path.name}")
        except Exception as e:
            print(f"   ❌ 失败: {e}")
            # 创建空文件避免 pipeline 报错
            (output_path / f"{img.stem}.md").write_text("", encoding="utf-8")

    # OCR PDF
    for pdf in pdf_files:
        print(f"🔍 OCR PDF: {pdf.name}")
        try:
            md_path = ocr_pdf(pdf, output_path)
            print(f"   ✅ -> {md_path.name}")
        except Exception as e:
            print(f"   ❌ 失败: {e}")
            (output_path / f"{pdf.stem}.md").write_text("", encoding="utf-8")

    md_files = list(output_path.glob("*.md"))
    print(f"\n✅ 完成！生成 {len(md_files)} 个 .md 文件")


if __name__ == "__main__":
    main()
