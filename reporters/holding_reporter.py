# -*- coding: utf-8 -*-
"""
持仓明细报表：产出「完整表」与「标准表」。
列顺序与旧版 run_holding.py 完全一致，确保收敛后黄金 diff 精确一致。
"""
from pathlib import Path
import pandas as pd

from core.models import HoldingDetail
from core.rules import extract_short_name

# 完整表列顺序（与旧 run_holding 的 all_results 字典顺序一致）
FULL_COLUMNS = [
    '项目代码', '项目名称', '表格名称', '工作表名称', '成本科目行号', '成本科目代码',
    '成本科目名称', '目标行号', '目标相对位置', '科目代码', '投资标的', '匹配关键词',
    '数量', '单位成本', '成本', '成本占净值%', '市价', '市值_原始', '市值占净值%_原始',
    '估值增值', '停牌信息',
]

# 标准表列顺序
STD_COLUMNS = [
    '项目代码', '项目名称', '简称', '目标行号', '科目代码', '投资标的', '匹配关键词',
    '市值_原始', '市值占净值%_原始',
]


class HoldingReporter:
    def __init__(self, output_dir: Path = None):
        self.output_dir = Path(output_dir) if output_dir else None

    @staticmethod
    def _to_full_row(h: HoldingDetail) -> dict:
        return {
            '项目代码': h.project_code,
            '项目名称': h.project_name,
            '表格名称': h.table_name,
            '工作表名称': h.sheet_name,
            '成本科目行号': h.cost_row,
            '成本科目代码': h.cost_code,
            '成本科目名称': h.cost_name,
            '目标行号': h.source_row,
            '目标相对位置': h.rel_pos,
            '科目代码': h.account_code,
            '投资标的': h.target_name,
            '匹配关键词': h.match_keyword,
            '数量': h.quantity,
            '单位成本': h.unit_cost,
            '成本': h.cost,
            '成本占净值%': h.cost_nav_pct,
            '市价': h.market_price,
            '市值_原始': h.mv_raw,
            '市值占净值%_原始': h.pct_raw,
            '估值增值': h.valuation_add,
            '停牌信息': h.halt_info,
        }

    def to_full_frame(self, holdings: list) -> pd.DataFrame:
        rows = [self._to_full_row(h) for h in holdings]
        df = pd.DataFrame(rows)
        return df[[c for c in FULL_COLUMNS if c in df.columns]]

    def to_std_frame(self, holdings: list) -> pd.DataFrame:
        df = self.to_full_frame(holdings)
        if '简称' not in df.columns:
            df['简称'] = df['项目名称'].apply(extract_short_name).str.strip()
        df['简称'] = df['简称'].astype(str).str.strip()
        df['投资标的'] = df['投资标的'].astype(str).str.strip()
        cols = [c for c in STD_COLUMNS if c in df.columns]
        return df[cols].copy()

    def write_full(self, holdings: list, out_path: Path) -> Path:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        self.to_full_frame(holdings).to_excel(out_path, index=False)
        return out_path

    def write_std(self, holdings: list, out_path: Path) -> Path:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        self.to_std_frame(holdings).to_excel(out_path, index=False)
        return out_path
