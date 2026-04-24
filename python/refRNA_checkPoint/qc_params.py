"""
从 params.toml 加载质控参数：阈值区间与按产品类型的文件清单。
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Union

try:
    import tomllib  # Python 3.11+
except ImportError:
    import tomli as tomllib  # type: ignore

Number = Union[int, float]


def _config_path(explicit: Optional[str] = None) -> Path:
    if explicit:
        return Path(explicit)
    return Path(__file__).resolve().parent / "params.toml"


@lru_cache(maxsize=8)
def _load_raw(path_str: str) -> dict:
    path = Path(path_str)
    with path.open("rb") as f:
        return tomllib.load(f)


def load_raw(config_path: Optional[str] = None) -> dict:
    return _load_raw(str(_config_path(config_path)))


def resolve_profile_key(species: str, group_num: int) -> str:
    """与旧 Params.py 一致：物种 + 分组数 → 配置节名。"""
    if species == "homo_sapiens" and group_num > 1:
        return "multiGroup_hsa"
    if species == "homo_sapiens" and group_num == 1:
        return "singleGroup_hsa"
    if species in ("mus_musculus", "rattus_norvegicus") and group_num > 1:
        return "multiGroup_mmu"
    if species in ("mus_musculus", "rattus_norvegicus") and group_num == 1:
        return "singleGroup_mmu"
    if species not in ("homo_sapiens", "mus_musculus", "rattus_norvegicus") and group_num > 1:
        return "multiGroup_other"
    if species not in ("homo_sapiens", "mus_musculus", "rattus_norvegicus") and group_num == 1:
        return "singleGroup_other"
    raise ValueError(f"无法解析项目类型: species={species!r}, group_num={group_num}")


def get_thresholds(config_path: Optional[str] = None) -> Dict[str, Any]:
    """返回 [thresholds] 表（含 DiffGeneNum 标量）。"""
    return dict(load_raw(config_path)["thresholds"])


def get_file_check_list(
    product: str,
    profile_key: str,
    config_path: Optional[str] = None,
) -> List[str]:
    if product not in ("standard", "cloud"):
        raise ValueError("product 须为 'standard' 或 'cloud'")
    raw = load_raw(config_path)
    try:
        return list(raw["file_lists"][product][profile_key])
    except KeyError as e:
        raise KeyError(f"未找到 file_lists.{product}.{profile_key}") from e


def value_in_interval(x: Number, spec: Any) -> bool:
    """
    判断标量是否在 TOML 区间 [min, max] 内（闭区间）。
    spec 为 dict 时读 min/max；省略的边界表示无限制。
    """
    if not isinstance(spec, Mapping):
        raise TypeError(f"阈值须为 {{min/max}} 区间表，收到: {type(spec)!r}")
    lo = spec.get("min")
    hi = spec.get("max")
    if lo is not None and x < lo:
        return False
    if hi is not None and x > hi:
        return False
    return True


def diff_gene_num_threshold(config_path: Optional[str] = None) -> int:
    t = get_thresholds(config_path)
    n = t.get("DiffGeneNum")
    if n is None:
        raise KeyError("thresholds 中缺少 DiffGeneNum")
    return int(n)
