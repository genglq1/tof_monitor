#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
穿透报告解析器（复刻旧版 run_penetration.py）。

逐字节复刻旧脚本逻辑，收敛到 core 框架：
- 在「信托文件夹」下递归查找每个下投产品的底层估值表
- 解析底层估值表的 市值占比 列，按固收/权益关键词归集贡献
- 结合持仓标准表的持有占比，计算穿透固收/权益总占比
- 产出与旧脚本完全一致的报告数据（由 reporters/penetration_reporter 写出）

为与旧脚本黄金 diff 精确一致，关键词列表、匹配优先级、取值逻辑、列格式
均与原逻辑完全一致。
"""
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple
import re
import pandas as pd


# ==================== 固收 / 权益 关键词（与旧 run_penetration 完全一致） ====================
FIXED_INCOME_KEYWORDS = [
    '银行存款', '结算备付金', '存出保证金', '债券', '国债', '金融债',
    '企业债', '中期票据', '短期融资券', '资产支持证券', '买入返售金融资产',
    '应收利息', '其他货币资金', '持有至到期投资', '清算备付金',
    '保证金账户', '买入返售金额资产', '应收股利', '应收申购款', '应收TA申购款',
    '交易性债券投资', '以公允价值计量且其变动计入当期损益的债券投资'
]
EQUITY_KEYWORDS = [
    '股票', '基金', '交易性股票投资', '交易类基金投资', '权证', '可转债',
    '期货', '期权', '衍生工具', '股指期货', '商品期货',
    '以公允价值计量且其变动计入当期损益的股票投资', '股票投资',
    '交易性基金投资', '以公允价值计量且其变动计入当期损益的基金投资', '套期工具'
]


@dataclass
class PenetrationResult:
    """一次穿透报告生成结果（供 reporter 写出）。"""
    success: bool = False
    df: Optional[pd.DataFrame] = None
    total_fixed: float = 0.0
    total_equity: float = 0.0
    trust_name: str = ""
    total_asset_str: str = ""
    code: str = ""
    query_date: str = ""


class PenetrationParser:
    FIXED_INCOME_KEYWORDS = FIXED_INCOME_KEYWORDS
    EQUITY_KEYWORDS = EQUITY_KEYWORDS

    # -------- 复刻 run_penetration.find_trust_dir --------
    def find_trust_dir(self, keyword, search_dirs: List[Path]) -> Tuple[Optional[Path], Optional[str]]:
        keyword_lower = keyword.lower()
        for search_dir in search_dirs:
            search_dir = Path(search_dir)
            if not search_dir.exists():
                continue
            for d in search_dir.iterdir():
                if not d.is_dir():
                    continue
                parts = d.name.split('_')
                code = parts[0] if parts and re.match(r'^[A-Z0-9]{5,8}$', parts[0].upper()) else None
                if code and code.lower() == keyword_lower:
                    return d, code
                if keyword_lower in d.name.lower():
                    return d, code
        return None, None

    # -------- 复刻 run_penetration.get_total_asset --------
    def get_total_asset(self, project_code, valuation_stats_file) -> Optional[float]:
        valuation_stats_file = Path(valuation_stats_file)
        if not valuation_stats_file.exists():
            return None
        try:
            df = pd.read_excel(valuation_stats_file)
            row = df[df['项目代码'].astype(str).str.upper() == str(project_code).upper()]
            if row.empty:
                return None
            val = row.iloc[0]['资产类合计_市值']
            return float(val) if pd.notna(val) else None
        except Exception:
            return None

    # -------- 复刻 run_penetration.get_holdings_by_code --------
    def get_holdings_by_code(self, project_code, holding_std_file) -> Optional[pd.DataFrame]:
        holding_std_file = Path(holding_std_file)
        if not holding_std_file.exists():
            return None
        df = pd.read_excel(holding_std_file)
        required = ['项目代码', '投资标的', '市值占净值%_原始']
        for col in required:
            if col not in df.columns:
                return None
        mask = df['项目代码'].astype(str).str.upper() == str(project_code).upper()
        cols_to_get = ['投资标的', '市值占净值%_原始']
        if '简称' in df.columns:
            cols_to_get.append('简称')
        sub = df.loc[mask, cols_to_get].copy()
        if sub.empty:
            return None
        sub.rename(columns={'市值占净值%_原始': '持有占比'}, inplace=True)
        sub['持有占比'] = pd.to_numeric(sub['持有占比'], errors='coerce')
        return sub

    # -------- 复刻 run_penetration.find_file_recursive --------
    def _find_file_recursive(self, folder: Path, pattern: str) -> Optional[Path]:
        try:
            for f in folder.glob(pattern):
                return f
            for subdir in folder.iterdir():
                if subdir.is_dir():
                    result = self._find_file_recursive(subdir, pattern)
                    if result:
                        return result
        except PermissionError:
            pass
        return None

    # -------- 复刻 run_penetration.find_product_valuation --------
    def find_product_valuation(self, trust_folder, query_date, product_name, short_name=None) -> Optional[Path]:
        clean_name = product_name.replace('私募证券投资基金', '').replace('私募基金', '').strip()
        clean_name = clean_name.replace('一', '1').replace('二', '2').replace('三', '3').replace('四', '4')
        date_formats = [query_date, f"{query_date[:4]}-{query_date[4:6]}-{query_date[6:]}"]
        names_to_try = []
        if short_name:
            short_clean = short_name.replace('私募证券投资基金', '').replace('私募基金', '').strip()
            short_clean = short_clean.replace('一', '1').replace('二', '2').replace('三', '3').replace('四', '4')
            names_to_try.extend([short_name, short_clean])
        names_to_try.extend([clean_name, product_name])
        for name in names_to_try:
            for date_str in date_formats:
                pattern = f"*{name}*{date_str}*.xls*"
                f = self._find_file_recursive(Path(trust_folder), pattern)
                if f:
                    return f
        return None

    # -------- 复刻 run_penetration.extract_ratios --------
    def extract_ratios(self, valuation_file) -> Tuple[float, float, float, float]:
        try:
            df = pd.read_excel(valuation_file, sheet_name=0, header=None)
            code_col = name_col = ratio_col = None
            header_row = None
            for i in range(min(30, len(df))):
                for j in range(df.shape[1]):
                    cell = str(df.iloc[i, j]) if pd.notna(df.iloc[i, j]) else ""
                    if '科目代码' in cell and code_col is None:
                        code_col = j
                    if '科目名称' in cell and name_col is None:
                        name_col = j
                    if '市值占比' in cell and ratio_col is None:
                        ratio_col = j
                if code_col is not None and name_col is not None and ratio_col is not None:
                    header_row = i
                    break
            if code_col is None:
                code_col = 0
            if name_col is None:
                name_col = 1
            if ratio_col is None:
                ratio_col = 8
            if header_row is None:
                header_row = 4

            all_vals = []
            for i in range(header_row + 1, len(df)):
                code = str(df.iloc[i, code_col]) if pd.notna(df.iloc[i, code_col]) else ""
                if not re.match(r'^\d{4}$', code.strip()):
                    continue
                val = df.iloc[i, ratio_col]
                try:
                    v = float(val)
                    if v != 0:
                        all_vals.append(v)
                except Exception:
                    pass

            need_scale = True
            if all_vals:
                avg = sum(all_vals) / len(all_vals)
                if avg > 1:
                    need_scale = False

            fixed_raw = equity_raw = 0.0
            for i in range(header_row + 1, len(df)):
                code = str(df.iloc[i, code_col]) if pd.notna(df.iloc[i, code_col]) else ""
                if not re.match(r'^\d{4}$', code.strip()):
                    continue
                name = str(df.iloc[i, name_col]) if pd.notna(df.iloc[i, name_col]) else ""
                if not name.strip():
                    continue
                val = df.iloc[i, ratio_col]
                try:
                    ratio = float(val)
                except Exception:
                    continue
                if any(kw in name for kw in self.FIXED_INCOME_KEYWORDS):
                    fixed_raw += ratio
                elif any(kw in name for kw in self.EQUITY_KEYWORDS):
                    equity_raw += ratio

            if need_scale:
                fixed_contrib = fixed_raw
                equity_contrib = equity_raw
                fixed_disp = fixed_raw * 100
                equity_disp = equity_raw * 100
            else:
                fixed_contrib = fixed_raw / 100
                equity_contrib = equity_raw / 100
                fixed_disp = fixed_raw
                equity_disp = equity_raw
            return fixed_contrib, equity_contrib, fixed_disp, equity_disp
        except Exception:
            return 0.0, 0.0, 0.0, 0.0

    # -------- 复刻 run_penetration.generate_report（计算部分，不写文件） --------
    def generate(self, project_code, query_date, holding_std_file, valuation_stats_file,
                 search_dirs: List[Path]) -> PenetrationResult:
        trust_dir, code = self.find_trust_dir(project_code, search_dirs)
        if trust_dir is None:
            return PenetrationResult(success=False, code=project_code, query_date=query_date)
        if code is None:
            code = project_code

        trust_name = trust_dir.name

        total_asset = self.get_total_asset(code, valuation_stats_file)
        total_asset_str = f"{total_asset:,.2f}" if total_asset else ""

        holdings = self.get_holdings_by_code(code, holding_std_file)
        if holdings is None or holdings.empty:
            return PenetrationResult(success=False, code=code, query_date=query_date,
                                      trust_name=trust_name, total_asset_str=total_asset_str)

        holdings = holdings.copy()
        holdings['固收贡献'] = 0.0
        holdings['权益贡献'] = 0.0
        holdings['固收显示'] = 0.0
        holdings['权益显示'] = 0.0

        for idx, row in holdings.iterrows():
            product_name = row['投资标的']
            short_name = row.get('简称', '')
            valuation_file = self.find_product_valuation(trust_dir, query_date, product_name, short_name)
            if valuation_file is None:
                fixed_contrib = equity_contrib = fixed_disp = equity_disp = 0.0
            else:
                fixed_contrib, equity_contrib, fixed_disp, equity_disp = self.extract_ratios(valuation_file)

            holdings.at[idx, '固收贡献'] = fixed_contrib
            holdings.at[idx, '权益贡献'] = equity_contrib
            holdings.at[idx, '固收显示'] = fixed_disp
            holdings.at[idx, '权益显示'] = equity_disp

        total_fixed = (holdings['持有占比'] * holdings['固收贡献']).sum()
        total_equity = (holdings['持有占比'] * holdings['权益贡献']).sum()

        rows = []
        if len(holdings) == 1:
            r = holdings.iloc[0]
            rows.append({
                '目标产品名称': trust_name,
                '总市值': total_asset_str,
                '下投产品名称': r['投资标的'],
                '持有市值占比': f"{r['持有占比']:.4f}",
                '下投产品固收占比': f"{r['固收显示']:.4f}",
                '下投产品权益占比': f"{r['权益显示']:.4f}",
                '穿透固收占比': f"{total_fixed:.4f}",
                '穿透权益占比': f"{total_equity:.4f}",
            })
        else:
            first = holdings.iloc[0]
            rows.append({
                '目标产品名称': trust_name,
                '总市值': total_asset_str,
                '下投产品名称': first['投资标的'],
                '持有市值占比': f"{first['持有占比']:.4f}",
                '下投产品固收占比': f"{first['固收显示']:.4f}",
                '下投产品权益占比': f"{first['权益显示']:.4f}",
                '穿透固收占比': f"{total_fixed:.4f}",
                '穿透权益占比': f"{total_equity:.4f}",
            })
            for _, r in holdings.iloc[1:].iterrows():
                rows.append({
                    '目标产品名称': '',
                    '总市值': '',
                    '下投产品名称': r['投资标的'],
                    '持有市值占比': f"{r['持有占比']:.4f}",
                    '下投产品固收占比': f"{r['固收显示']:.4f}",
                    '下投产品权益占比': f"{r['权益显示']:.4f}",
                    '穿透固收占比': '',
                    '穿透权益占比': '',
                })

        df_final = pd.DataFrame(rows)
        return PenetrationResult(
            success=True,
            df=df_final,
            total_fixed=total_fixed,
            total_equity=total_equity,
            trust_name=trust_name,
            total_asset_str=total_asset_str,
            code=code,
            query_date=query_date,
        )
