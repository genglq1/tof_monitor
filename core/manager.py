#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
管理人全称回填（core 收敛版）

复刻旧版 manager_pipeline.py 的回填逻辑：
- 读 MANAGER_FULLNAME.xlsx，构建 (产品类型, 管理人关键字) -> 管理人全称 的映射
- 按关键字长度降序，优先匹配长关键字
- 对持仓表「投资标的」逐行识别产品类型，查表填「管理人名称」
- 在「投资标的」列之后插入「产品类型」「管理人名称」两列

为保证与旧脚本黄金 diff 精确一致，匹配优先级（精确类型 startswith → 不限类型 startswith → 含关键字）
与列插入位置均与原逻辑完全一致。
"""

from pathlib import Path
import pandas as pd

from core.rules import detect_product_type_with_cost


class ManagerFiller:
    """管理人全称回填器。"""

    def load_mapping(self, mapping_file):
        """读取 MANAGER_FULLNAME.xlsx，返回按关键字长度降序的 kw_list。

        返回: list[(产品类型, 管理人关键字, 管理人全称)]
        """
        mapping_file = Path(mapping_file)
        if not mapping_file.exists():
            raise FileNotFoundError(f"映射文档不存在: {mapping_file}")

        mapping = pd.read_excel(mapping_file, engine="openpyxl", dtype=str)
        for col in ["产品类型", "管理人关键字", "管理人全称"]:
            if col not in mapping.columns:
                raise ValueError(
                    f"映射文档缺少必要列: {col}, 实际列: {mapping.columns.tolist()}"
                )

        kw_list = []
        for _, r in mapping.iterrows():
            ptype = str(r["产品类型"]).strip()
            kw = str(r["管理人关键字"]).strip()
            full = str(r["管理人全称"]).strip()
            if not kw or kw == "nan" or not full or full == "nan":
                continue
            kw_list.append((ptype, kw, full))
        # 按关键字长度降序：匹配时先查"长关键字"再查"短关键字"
        kw_list.sort(key=lambda x: -len(x[1]))
        return kw_list

    def fill_frame(self, df: pd.DataFrame, mapping_file) -> pd.DataFrame:
        """对持仓 DataFrame 逐行回填「产品类型」「管理人名称」，返回 enriched DataFrame。

        df 必须含「投资标的」列；回填列插入到「投资标的」之后。
        """
        if "投资标的" not in df.columns:
            raise ValueError(f"持仓表缺少'投资标的'列, 实际列: {df.columns.tolist()}")

        kw_list = self.load_mapping(mapping_file)

        # 成本科目名称作为强信号辅助判型（完整表带此列；缺失时回退纯名称判型）
        has_cost = "成本科目名称" in df.columns

        type_col = []
        manager_col = []
        for idx, raw in enumerate(df["投资标的"]):
            name = str(raw).strip() if pd.notna(raw) else ""
            if not name:
                type_col.append("其他")
                manager_col.append("")
                continue
            cost_name = str(df.at[df.index[idx], "成本科目名称"]).strip() if has_cost else ""
            ptype = detect_product_type_with_cost(name, cost_name)
            # 1) 精确 (产品类型, 关键字) 优先
            full = ""
            for ex_ptype, ex_kw, ex_full in kw_list:
                if ex_ptype == ptype and name.startswith(ex_kw):
                    full = ex_full
                    break
            # 2) 兜底: 不限产品类型, 任意产品名以关键字开头
            if not full:
                for ex_ptype, ex_kw, ex_full in kw_list:
                    if name.startswith(ex_kw):
                        full = ex_full
                        break
            # 3) 再兜底: 关键字含在产品名中
            if not full:
                for ex_ptype, ex_kw, ex_full in kw_list:
                    if ex_kw in name:
                        full = ex_full
                        break
            type_col.append(ptype)
            manager_col.append(full)

        # 写回：在「投资标的」之后插入
        target_idx = df.columns.get_loc("投资标的") + 1
        for col in ["产品类型", "管理人名称"]:
            if col in df.columns:
                df = df.drop(columns=[col])
        df.insert(target_idx, "产品类型", type_col)
        df.insert(target_idx + 1, "管理人名称", manager_col)
        return df

    def fill_file(self, holding_full_path, mapping_file, output_path=None):
        """读持仓完整表 -> 回填 -> 写回（默认覆盖原文件）。"""
        holding_full_path = Path(holding_full_path)
        df = pd.read_excel(holding_full_path, engine="openpyxl")
        df = self.fill_frame(df, mapping_file)
        out = Path(output_path) if output_path else holding_full_path
        out.parent.mkdir(parents=True, exist_ok=True)
        df.to_excel(out, index=False, engine="openpyxl")
        return out
