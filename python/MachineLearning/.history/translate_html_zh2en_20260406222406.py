import os
import re
import sys
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from bs4 import BeautifulSoup, NavigableString, Comment, Tag

OpenAI = None  # type: ignore[assignment]
try:  # optional dependency
    from openai import OpenAI as _OpenAI

    OpenAI = _OpenAI  # type: ignore[misc]
except Exception:
    OpenAI = None  # type: ignore[assignment]


ZH_RE = re.compile(r"[\u4e00-\u9fff]")


def has_chinese(s: str) -> bool:
    return bool(s) and bool(ZH_RE.search(s))


def normalize_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def should_skip_text_node(node: NavigableString) -> bool:
    if isinstance(node, Comment):
        return True
    parent = getattr(node, "parent", None)
    if not parent or not getattr(parent, "name", None):
        return False
    return parent.name.lower() in {"script", "style", "code", "pre", "textarea", "kbd", "samp"}


def iter_translatable_text_nodes(soup: BeautifulSoup) -> List[NavigableString]:
    nodes: List[NavigableString] = []
    for node in soup.find_all(string=True):
        if should_skip_text_node(node):
            continue
        text = str(node)
        if not text or not text.strip():
            continue
        if has_chinese(text):
            nodes.append(node)
    return nodes


SAFE_ATTRS = ("title", "alt", "aria-label", "placeholder")


@dataclass(frozen=True)
class AttrTarget:
    tag: Tag
    attr: str


def iter_translatable_attributes(soup: BeautifulSoup) -> List[Tuple[AttrTarget, str]]:
    targets: List[Tuple[AttrTarget, str]] = []
    for tag in soup.find_all(True):
        for attr in SAFE_ATTRS:
            if not tag.has_attr(attr):
                continue
            val = tag.get(attr)
            if not isinstance(val, str):
                continue
            if not val.strip():
                continue
            if has_chinese(val):
                targets.append((AttrTarget(tag=tag, attr=attr), val))
    return targets


def chunk_items(items: List[Tuple[str, str]], max_chars: int = 3500) -> List[List[Tuple[str, str]]]:
    chunks: List[List[Tuple[str, str]]] = []
    cur: List[Tuple[str, str]] = []
    cur_len = 0
    for k, t in items:
        if len(t) > max_chars:
            t = t[:max_chars]
        if cur and cur_len + len(t) > max_chars:
            chunks.append(cur)
            cur = []
            cur_len = 0
        cur.append((k, t))
        cur_len += len(t)
    if cur:
        chunks.append(cur)
    return chunks


def _strip_code_fence(s: str) -> str:
    s = s.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*```$", "", s)
    return s.strip()


SYSTEM_PROMPT = (
    "You translate Chinese text fragments extracted from an RNA-seq HTML report into English.\n"
    "Write in an academic, literature-style tone suitable for a bioinformatics report/manuscript.\n"
    "Requirements:\n"
    "- Preserve meaning; do not add new claims.\n"
    "- Keep technical terms, gene names, pathway names, software names, parameters, units, and numbers unchanged.\n"
    "- If a fragment is mostly English with a few Chinese words, translate only the Chinese parts.\n"
)


def translate_batch_openai(client, pairs: List[Tuple[str, str]], model: str) -> Dict[str, str]:
    payload = [{"id": k, "zh": v} for k, v in pairs]
    system = SYSTEM_PROMPT + "- Output MUST be valid JSON: a list of objects {id, en} matching the input ids.\n"

    resp = client.responses.create(
        model=model,
        input=[
            {"role": "system", "content": system},
            {"role": "user", "content": f"Input JSON:\n{payload}\n\nReturn the translated JSON only."},
        ],
    )

    import json

    out_text = _strip_code_fence(resp.output_text)
    data = json.loads(out_text)
    out: Dict[str, str] = {}
    for item in data:
        out[str(item["id"])] = str(item["en"])
    return out


def translate_batch_argos(pairs: List[Tuple[str, str]]) -> Dict[str, str]:
    """
    Offline translation via Argos Translate.
    Install: pip install argostranslate
    Then download zh->en model once (see README below in usage message).
    """
    # Avoid Stanza auto-download (network) by using MiniSBD chunking.
    # This prevents argostranslate from trying to download Stanza models during translation.
    os.environ.setdefault("ARGOS_CHUNK_TYPE", "MINISBD")
    try:
        from argostranslate import translate as argos_translate  # type: ignore
    except Exception as e:  # pragma: no cover
        raise RuntimeError(
            "Missing dependency 'argostranslate'. Install with: pip install argostranslate"
        ) from e

    out: Dict[str, str] = {}
    for k, zh in pairs:
        out[k] = argos_translate.translate(zh, "zh", "en")
    return out


def _with_retries(fn, attempts: int = 5, base_sleep_s: float = 1.5):
    for attempt in range(attempts):
        try:
            return fn()
        except Exception:
            if attempt == attempts - 1:
                raise
            time.sleep(base_sleep_s * (attempt + 1))


def translate_html(in_path: str, out_path: str, model: str, engine: str) -> None:
    engine = engine.lower().strip()
    client = None
    if engine == "openai":
        if OpenAI is None:
            raise RuntimeError("Missing dependency 'openai'. Install with: pip install openai")
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("Missing OPENAI_API_KEY env var. Use --engine argos for offline mode.")
        base_url = os.environ.get("OPENAI_BASE_URL")
        client = OpenAI(api_key=api_key, base_url=base_url) if base_url else OpenAI(api_key=api_key)
    elif engine == "argos":
        client = None
    else:
        raise RuntimeError('Unsupported engine. Use --engine "argos" (offline) or --engine "openai".')

    with open(in_path, "r", encoding="utf-8", errors="ignore") as f:
        html = f.read()

    soup = BeautifulSoup(html, "lxml")

    text_nodes = iter_translatable_text_nodes(soup)
    attr_targets = iter_translatable_attributes(soup)

    # Build a unified queue of strings to translate; keys encode where to write back.
    text_items: List[Tuple[str, str]] = []
    for i, node in enumerate(text_nodes):
        text_items.append((f"t:{i}", normalize_ws(str(node))))

    attr_items: List[Tuple[str, str]] = []
    for i, (target, val) in enumerate(attr_targets):
        attr_items.append((f"a:{i}", normalize_ws(val)))

    all_items = text_items + attr_items
    if not all_items:
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(str(soup))
        return

    translations: Dict[str, str] = {}
    for chunk_idx, chunk in enumerate(chunk_items(all_items, max_chars=3500), 1):
        if engine == "openai":
            part = _with_retries(lambda: translate_batch_openai(client, chunk, model=model))
        else:
            part = _with_retries(lambda: translate_batch_argos(chunk), attempts=3, base_sleep_s=0.5)
        translations.update(part)
        print(f"Translated chunk {chunk_idx}")

    # Write back text nodes; preserve original leading/trailing whitespace
    for i, node in enumerate(text_nodes):
        key = f"t:{i}"
        en = translations.get(key)
        if not en:
            continue
        original = str(node)
        left_ws = re.match(r"^\s*", original).group(0)
        right_ws = re.match(r".*?(\s*)$", original, flags=re.S).group(1)
        node.replace_with(NavigableString(left_ws + en.strip() + right_ws))

    # Write back safe attributes
    for i, (target, original_val) in enumerate(attr_targets):
        key = f"a:{i}"
        en = translations.get(key)
        if not en:
            continue
        # Preserve surrounding whitespace (rare in attributes, but safe)
        left_ws = re.match(r"^\s*", original_val).group(0)
        right_ws = re.match(r".*?(\s*)$", original_val, flags=re.S).group(1)
        target.tag[target.attr] = left_ws + en.strip() + right_ws

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(str(soup))


def main(argv: Optional[List[str]] = None) -> int:
    argv = argv or sys.argv[1:]
    if len(argv) < 2:
        print("Usage: python translate_html_zh2en.py <input.html> <output.html> [model] [--engine openai|argos]")
        print('Example (offline): python translate_html_zh2en.py RNA-seq-report.html RNA-seq-report.en.html --engine argos')
        print('Example (OpenAI):  python translate_html_zh2en.py RNA-seq-report.html RNA-seq-report.en.html "gpt-4.1-mini" --engine openai')
        return 2

    in_path = argv[0]
    out_path = argv[1]
    # parse optional args
    engine = "argos"
    model = "gpt-4.1-mini"
    rest = argv[2:]
    # If the next token doesn't look like an option, treat as model
    if rest and not rest[0].startswith("--"):
        model = rest[0]
        rest = rest[1:]
    if rest:
        for i, tok in enumerate(rest):
            if tok == "--engine" and i + 1 < len(rest):
                engine = rest[i + 1]
    translate_html(in_path, out_path, model=model, engine=engine)
    print(f"Done. Wrote: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

