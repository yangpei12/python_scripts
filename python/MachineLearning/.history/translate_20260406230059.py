#!/usr/bin/env python3
"""
HTML 中文内容离线翻译脚本（中文 → 英文，学术风格后处理）
依赖：pip install argostranslate beautifulsoup4 lxml
首次运行会自动下载 zh→en 语言包（约 100MB），之后完全离线
"""

import re
import argostranslate.package
import argostranslate.translate
from bs4 import BeautifulSoup
from pathlib import Path


# ── 1. 自动安装 zh→en 语言包 ──────────────────────────────────────────────────
def ensure_zh_en_model():
    """首次运行自动下载安装中英语言包"""
    from_code, to_code = "zh", "en"

    # 检查是否已安装
    installed = argostranslate.package.get_installed_packages()
    already = any(p.from_code == from_code and p.to_code == to_code for p in installed)
    if already:
        print("✓ zh→en 语言包已就绪")
        return

    print("⬇ 正在下载 zh→en 语言包（首次约 100MB）...")
    argostranslate.package.update_package_index()
    available = argostranslate.package.get_available_packages()
    pkg = next(
        (p for p in available if p.from_code == from_code and p.to_code == to_code),
        None,
    )
    if pkg is None:
        raise RuntimeError("未找到 zh→en 语言包，请检查网络连接后重试")
    argostranslate.package.install_from_path(pkg.download())
    print("✓ 语言包安装完成")


# ── 2. 中文检测 ───────────────────────────────────────────────────────────────
def contains_chinese(text: str) -> bool:
    return bool(re.search(r'[\u4e00-\u9fff\u3400-\u4dbf]', text))


# ── 3. 学术风格后处理 ─────────────────────────────────────────────────────────
ACADEMIC_REPLACEMENTS = [
    # 口语 → 学术
    (r'\bshows?\b',         'demonstrates'),
    (r'\bused\b',           'employed'),
    (r'\buse\b',            'utilize'),
    (r'\bget\b',            'obtain'),
    (r'\bgot\b',            'obtained'),
    (r'\bfind out\b',       'identify'),
    (r'\bfound out\b',      'identified'),
    (r'\blook at\b',        'examine'),
    (r'\bbig\b',            'substantial'),
    (r'\bsmall\b',          'minimal'),
    (r'\bhelp\b',           'facilitate'),
    (r'\bthings?\b',        'factors'),
    (r'\ba lot of\b',       'a considerable number of'),
    (r'\blots of\b',        'numerous'),
    (r'\bbut\b',            'however,'),
    (r'\bso\b',             'therefore,'),
    (r'\bAlso[,]?\b',       'Furthermore,'),
    (r'\bIn addition[,]?\b','Moreover,'),
    # 首字母大写修正（句首）
]

def academic_polish(text: str) -> str:
    """对翻译结果做学术风格替换"""
    for pattern, replacement in ACADEMIC_REPLACEMENTS:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    # 确保句首大写
    text = re.sub(r'(?<=[.!?]\s)([a-z])', lambda m: m.group(1).upper(), text)
    return text


# ── 4. 核心翻译函数 ───────────────────────────────────────────────────────────
def translate_zh_to_en(text: str) -> str:
    """翻译单段文本（含中文才翻译）"""
    if not contains_chinese(text):
        return text
    translated = argostranslate.translate.translate(text.strip(), "zh", "en")
    return academic_polish(translated)


# ── 5. 遍历 HTML 节点并翻译 ───────────────────────────────────────────────────
# 跳过这些标签（不翻译代码、脚本等）
SKIP_TAGS = {"script", "style", "code", "pre", "kbd", "var", "math"}

def translate_html(input_path: str, output_path: str):
    src = Path(input_path).read_text(encoding="utf-8")
    soup = BeautifulSoup(src, "lxml")

    translated_count = 0

    for element in soup.find_all(string=True):
        # 跳过父标签为代码类的节点
        if element.parent.name in SKIP_TAGS:
            continue

        original = str(element)
        if not contains_chinese(original):
            continue

        translated = translate_zh_to_en(original)
        element.replace_with(translated)
        translated_count += 1
        print(f"  [{translated_count}] {original[:30].strip()!r} → {translated[:40].strip()!r}")

    Path(output_path).write_text(str(soup), encoding="utf-8")
    print(f"\n✓ 翻译完成，共处理 {translated_count} 个文本节点")
    print(f"✓ 输出文件：{output_path}")


# ── 6. 入口 ───────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("用法：python translate_html.py input.html [output.html]")
        sys.exit(1)

    input_file  = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else input_file.replace(".html", "_en.html")

    ensure_zh_en_model()
    translate_html(input_file, output_file)