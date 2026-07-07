#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
估值统计解析器

逐字节复刻旧版 run_valuation.py 的逻辑，收敛到 core 框架：
- 读取每个估值表的「估值表明细表」工作表（无表头，固定列索引）
- 抽取 银行存款 / 信托保障基金 / 证券投资合计 / 实收信托 / 负债类合计 / 资产类合计 的市值与占比
- 输出 信托产品估值统计结果 工作表（下游穿透强依赖）

为保证与旧脚本黄金 diff 精确一致，列顺序、取值列索引(7/8)、缺失值回退 0、空表格判定
均与原逻辑完全一致。
"""

from pathlib import Path
from dataclasses import dataclass, field
import pandas as pd

from utils.helpers import extract_project_info


@dataclass
class ValuationStat:
    """单份估值表的统计结果（字段顺序与旧 run_valuation 输出列一致）。"""
    project_code: str = ""
    project_name: str = ""
    valuation_date: object = None
    bank_deposit_mv: float = 0.0
    bank_deposit_pct: float = 0.0
    trust_fund_mv: float = 0.0
    trust_fund_pct: float = 0.0
    security_invest_mv: float = 0.0
    security_invest_pct: float = 0.0
    paid_in_trust_mv: float = 0.0
    paid_in_trust_pct: float = 0.0
    liability_total_mv: float = 0.0
    liability_total_pct: float = 0.0
    asset_total_mv: float = 0.0
    asset_total_pct: float = 0.0

    def to_row(self):
        return {
            '项目代码': self.project_code,
            '项目名称': self.project_name,
            '估值日期': self.valuation_date,
            '银行存款_市值': self.bank_deposit_mv,
            '银行存款_市值占净值%': self.bank_deposit_pct,
            '信托保障基金_市值': self.trust_fund_mv,
            '信托保障基金_市值占净值%': self.trust_fund_pct,
            '证券投资合计_市值': self.security_invest_mv,
            '证券投资合计_市值占净值%': self.security_invest_pct,
            '实收信托_市值': self.paid_in_trust_mv,
            '实收信托_市值占净值%': self.paid_in_trust_pct,
            '负债类合计_市值': self.liability_total_mv,
            '负债类合计_市值占净值%': self.liability_total_pct,
            '资产类合计_市值': self.asset_total_mv,
            '资产类合计_市值占净值%': self.asset_total_pct,
        }


COLUMNS_ORDER = [
    '项目代码', '项目名称', '估值日期',
    '银行存款_市值', '银行存款_市值占净值%',
    '信托保障基金_市值', '信托保障基金_市值占净值%',
    '证券投资合计_市值', '证券投资合计_市值占净值%',
    '实收信托_市值', '实收信托_市值占净值%',
    '负债类合计_市值', '负债类合计_市值占净值%',
    '资产类合计_市值', '资产类合计_市值占净值%'
]


def _is_empty_valuation(df):
    """复刻 run_valuation.is_empty_valuation：无表头或无关键数据行则视为空。"""
    if df is None or len(df) == 0:
        return True
    has_header = False
    for idx, row in df.iterrows():
        if '科目代码' in str(row.iloc[0]) or '科目名称' in str(row.iloc[1]):
            has_header = True
            break
    if not has_header:
        return True
    has_data = False
    for keyword in ['银行存款', '资产类合计', '实收信托']:
        if df.iloc[:, 1].astype(str).str.contains(keyword, na=False).any():
            has_data = True
            break
    return not has_data


def _read_valuation_data(file_path):
    """复刻 run_valuation.read_valuation_data。"""
    try:
        return pd.read_excel(file_path, sheet_name='估值表明细表', header=None)
    except Exception:
        try:
            return pd.read_excel(file_path, header=None)
        except Exception as e:
            print(f"  读取出错: {e}")
            return None


def _extract_value(df, keyword, search_column=1):
    """复刻 run_valuation.extract_value：取首个匹配行的 iloc[7]/iloc[8]。"""
    mask = df.iloc[:, search_column].astype(str).str.contains(keyword, na=False)
    matched = df[mask]
    if len(matched) > 0:
        row = matched.iloc[0]
        mv = row.iloc[7] if pd.notna(row.iloc[7]) else 0
        mvp = row.iloc[8] if pd.notna(row.iloc[8]) else 0
        try:
            mv = float(mv)
        except Exception:
            mv = 0
        try:
            mvp = float(mvp)
        except Exception:
            mvp = 0
        return mv, mvp
    return 0, 0


def _extract_trust_fund(df):
    """复刻 run_valuation.extract_trust_fund。"""
    mask = df.iloc[:, 1].astype(str).str.contains('信托保障基金', na=False)
    matched = df[mask]
    for _, row in matched.iterrows():
        market_price = row.iloc[6]
        if pd.notna(market_price) and market_price != '':
            try:
                return float(row.iloc[7]) if pd.notna(row.iloc[7]) else 0, \
                       float(row.iloc[8]) if pd.notna(row.iloc[8]) else 0
            except Exception:
                pass
    return 0, 0


def _analyze_single_file(file_path):
    """复刻 run_valuation.analyze_single_file，返回 ValuationStat 或 None（空表）。"""
    filename = Path(file_path).name
    project_code, project_name, valuation_date = extract_project_info(filename)
    df = _read_valuation_data(file_path)
    if df is None or _is_empty_valuation(df):
        print(f"  空表格，已跳过")
        return None

    stat = ValuationStat(
        project_code=project_code,
        project_name=project_name,
        valuation_date=valuation_date,
    )

    bd_v, bd_p = _extract_value(df, '银行存款', search_column=1)
    stat.bank_deposit_mv, stat.bank_deposit_pct = bd_v, bd_p

    tf_v, tf_p = _extract_trust_fund(df)
    stat.trust_fund_mv, stat.trust_fund_pct = tf_v, tf_p

    si_v, si_p = _extract_value(df, '证券投资合计', search_column=0)
    stat.security_invest_mv, stat.security_invest_pct = si_v, si_p

    pt_v, pt_p = _extract_value(df, '实收信托', search_column=0)
    stat.paid_in_trust_mv, stat.paid_in_trust_pct = pt_v, pt_p

    li_v, li_p = _extract_value(df, '负债类合计', search_column=0)
    stat.liability_total_mv, stat.liability_total_pct = li_v, li_p

    at_v, at_p = _extract_value(df, '资产类合计', search_column=0)
    stat.asset_total_mv, stat.asset_total_pct = at_v, at_p

    return stat


class ValuationStatsParser:
    """估值统计解析器（复刻 run_valuation）。"""

    def parse(self, input_dir):
        """扫描目录下 *估值表_*.xls*，返回 (stats: list[ValuationStat], empty_files: list[dict])。"""
        input_dir = Path(input_dir)
        valuation_files = list(input_dir.glob('*估值表_*.xls*'))
        print(f"找到 {len(valuation_files)} 个估值表文件")

        stats = []
        empty_files = []

        for i, file_path in enumerate(valuation_files, 1):
            print(f"[{i}/{len(valuation_files)}] 处理: {file_path.name}")
            try:
                stat = _analyze_single_file(file_path)
                if stat is not None:
                    stats.append(stat)
                else:
                    filename = file_path.name
                    project_code, project_name, valuation_date = extract_project_info(filename)
                    empty_files.append({
                        '文件名': filename,
                        '项目代码': project_code,
                        '项目名称': project_name,
                        '估值日期': valuation_date,
                    })
            except Exception as e:
                print(f"  处理出错: {e}")

        print(f"\n成功处理 {len(stats)} 个有效文件")
        if empty_files:
            print(f"跳过 {len(empty_files)} 个空表格文件")
        return stats, empty_files
