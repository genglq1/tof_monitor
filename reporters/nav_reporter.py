#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
净值分析报表（P5）：复刻旧 analyze_nav.py 的 Excel 写出逻辑。
"""
import os
import pandas as pd
from pathlib import Path


class NavReporter:
    """将净值分析指标写出为 Excel，复刻旧 analyze_directory 的格式化与列顺序。"""

    def write_report(self, metrics_list, output_dir):
        """
        :param metrics_list: NavAnalyzer.analyze_directory 返回的指标字典列表
        :param output_dir: 输出目录（与 PNG 同目录）
        :return: 写出的 Excel 路径
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        if not metrics_list:
            return None

        df_result = pd.DataFrame(metrics_list)

        # 调整列顺序（与旧逻辑一致）
        year_cols = [c for c in df_result.columns if '年收益' in c and c != '年化收益率']
        other_cols = [c for c in df_result.columns if c not in year_cols]
        df_result = df_result[other_cols + year_cols]

        # 格式化
        pct_cols = ['最大回撤', '年化波动率', '年化收益率', '总收益率'] + year_cols
        for col in pct_cols:
            if col in df_result.columns:
                df_result[col] = df_result[col].apply(
                    lambda x: f'{x:.2%}' if pd.notnull(x) and x != '' else '')

        for col in ['卡玛比率', '夏普比率']:
            if col in df_result.columns:
                df_result[col] = df_result[col].apply(
                    lambda x: f'{x:.2f}' if pd.notnull(x) and x != '' else '')

        output_file = os.path.join(str(output_dir), '净值分析结果.xlsx')
        df_result.to_excel(output_file, index=False)
        return Path(output_file)
