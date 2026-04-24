"""
质控参数已迁移至 params.toml（与 qc_params 模块）。

旧版通过类属性读取阈值的方式已移除；请直接编辑 params.toml 中的 [thresholds] 与各 file_lists 节。
"""

raise ImportError(
    "Params.py 已废弃：请使用 params.toml + qc_params.get_thresholds() / get_file_check_list()，"
    "或通过 Check_Point.py --product 运行质控。"
)
