#!/usr/bin/env python3
"""
HTML 中文内容离线翻译脚本（中文 → 英文，学术风格后处理）
依赖：pip install argostranslate beautifulsoup4 lxml
"""

import os
import re
import sys

# ── 禁止 argostranslate 任何联网行为 ──────────────────────────────────────────
os.environ["ARGOS_TRANSLATE_PACKAGE_INDEX"] = ""
os.environ["ARGOS_DEVICE_TYPE"] = "cpu"

import argostranslate.package
import argostranslate.translate
from bs4 import BeautifulSoup
from pathlib import Path


# ── 1. 语言包安装（完全离线）─────────────────────────────────────────────────
def ensure_zh_en_model(local_model_path: str = None):
    installed = argostranslate.package.get_installed_packages()
    already = any(p.from_code == "zh" and p.to_code == "en" for p in installed)
    if already:
        print("✓ zh→en 语言包已就绪")
        return

    if local_model_path is None:
        raise RuntimeError(
            "语言包未安装，请手动下载 .argosmodel 文件后以第三个参数传入：\n"
            "  python translate_html.py input.html output.html /path/to/translate-zh_en.argosmodel\n"
            "下载地址：https://www.argosopentech.com/argospm/index/"
        )

    print(f"📦 从本地安装语言包：{local_model_path}")
    argostranslate.package.install_from_path(local_model_path)
    print("✓ 安装完成")


# ── 2. 初始化离线翻译器 ───────────────────────────────────────────────────────
TRANSLATOR = None

def get_translator():
    global TRANSLATOR
    if TRANSLATOR is not None:
        return TRANSLATOR
    installed = argostranslate.package.get_installed_packages()
    pkg = next((p for p in installed if p.from_code == "zh" and p.to_code == "en"), None)
    if pkg is None:
        raise RuntimeError("未找到已安装的 zh→en 语言包")
    TRANSLATOR = argostranslate.translate.get_translation_from_codes("zh", "en")
    return TRANSLATOR


# ── 3. 中文检测 ───────────────────────────────────────────────────────────────
def contains_chinese(text: str) -> bool:
    return bool(re.search(r'[\u4e00-\u9fff\u3400-\u4dbf]', text))


# ── 4. 学术风格后处理 ─────────────────────────────────────────────────────────
ACADEMIC_REPLACEMENTS = [
    (r'\bshows?\b',          'demonstrates'),
    (r'\bused\b',            'employed'),
    (r'\buse\b',             'utilize'),
    (r'\bget\b',             'obtain'),
    (r'\bgot\b',             'obtained'),
    (r'\bfind out\b',        'identify'),
    (r'\bfound out\b',       'identified'),
    (r'\blook at\b',         'examine'),
    (r'\bbig\b',             'substantial'),
    (r'\bsmall\b',           'minimal'),
    (r'\bhelp\b',            'facilitate'),
    (r'\bthings?\b',         'factors'),
    (r'\ba lot of\b',        'a considerable number of'),
    (r'\blots of\b',         'numerous'),
    (r'\bbut\b',             'however,'),
    (r'\bso\b',              'therefore,'),
    (r'\bAlso[,]?\b',        'Furthermore,'),
    (r'\bIn addition[,]?\b', 'Moreover,'),
]

def academic_polish(text: str) -> str:
    for pattern, replacement in ACADEMIC_REPLACEMENTS:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    # 句首大写
    text = re.sub(r'(?<=[.!?]\s)([a-z])', lambda m: m.group(1).upper(), text)
    return text


# ── 5. 翻译单段文本 ───────────────────────────────────────────────────────────
def translate_zh_to_en(text: str) -> str:
    if not contains_chinese(text):
        return text
    translator = get_translator()
    translated = translator.translate(text.strip())
    return academic_polish(translated)


# ── 6. 遍历 HTML 节点并翻译 ───────────────────────────────────────────────────
SKIP_TAGS = {"script", "style", "code", "pre", "kbd", "var", "math"}

def translate_html(input_path: str, output_path: str):
    src = Path(input_path).read_text(encoding="utf-8")
    soup = BeautifulSoup(src, "lxml")

    translated_count = 0

    for element in soup.find_all(string=True):
        if element.parent.name in SKIP_TAGS:
            continue

        original = str(element)
        if not contains_chinese(original):
            continue

        translated = translate_zh_to_en(original)
        element.replace_with(translated)
        translated_count += 1
        print(f"  [{translated_count}] {original[:40].strip()!r}")
        print(f"        → {translated[:60].strip()!r}")

    Path(output_path).write_text(str(soup), encoding="utf-8")
    print(f"\n✓ 翻译完成，共处理 {translated_count} 个文本节点")
    print(f"✓ 输出文件：{output_path}")


# ── 7. 入口 ───────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法：")
        print("  python translate_html.py input.html")
        print("  python translate_html.py input.html output.html")
        print("  python translate_html.py input.html output.html /path/to/translate-zh_en.argosmodel")
        sys.exit(1)

    input_file  = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else input_file.replace(".html", "_en.html")
    model_path  = sys.argv[3] if len(sys.argv) > 3 else None

    ensure_zh_en_model(local_model_path=model_path)
    translate_html(input_file, output_file)