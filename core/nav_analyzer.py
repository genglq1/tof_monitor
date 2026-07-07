#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
净值分析（P5）：逐字节复刻旧 analyze_nav.py 逻辑。

注意：旧脚本存在两处"缺陷"，为保持黄金 diff 一致必须原样保留：
1. aggregate_nav_files_by_product 对 xlsx 用 header=None 读取，导致 find_columns
   永远找不到列名（列名为整数索引），聚合分支实际不生效，仅单文件分支生效。
2. analyze_directory 的文件收集对每种扩展名同时 glob 小写与大写
   （*.xlsx 与 *.XLSX），在大小写不敏感的文件系统（Windows）上同一文件会被
   重复收集一次，因此每个产品会输出两行。
"""
import os
import re
import matplotlib
matplotlib.use("Agg")  # 无头环境绘图
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
from pathlib import Path
from collections import defaultdict

plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei']
plt.rcParams['axes.unicode_minus'] = False

RISK_FREE_RATE = 0.02
TRADING_DAYS = 252


class NavAnalyzer:
    """净值分析器，复刻 analyze_nav.py 的全部计算与绘图逻辑。"""

    RISK_FREE_RATE = RISK_FREE_RATE
    TRADING_DAYS = TRADING_DAYS

    def find_columns(self, df):
        """智能查找净值日期和累计净值列"""
        date_col = None
        nav_col = None

        for col in df.columns:
            col_str = str(col)
            if date_col is None and ('日期' in col_str or 'date' in col_str.lower()):
                date_col = col
            if nav_col is None and '累计' in col_str and ('净值' in col_str or 'nav' in col_str.lower()):
                nav_col = col

        return date_col, nav_col

    def aggregate_nav_files_by_product(self, directory):
        """按产品聚合目录下所有净值表文件（复刻旧逻辑，含 header=None 缺陷）"""
        extensions = ('.xlsx', '.xls', '.csv')
        files = []
        for ext in extensions:
            files.extend(Path(directory).glob(f'*{ext}'))
            files.extend(Path(directory).glob(f'*{ext.upper()}'))

        product_data = defaultdict(lambda: {'dates': [], 'navs': [], 'name': None})

        for file_path in files:
            filename = file_path.name

            if filename.endswith('.csv'):
                df = pd.read_csv(file_path, encoding='utf-8-sig')
            else:
                df = pd.read_excel(file_path, header=None)

            date_col, nav_col = self.find_columns(df)
            if date_col is None or nav_col is None:
                continue

            product_key = None
            product_name = None

            for col in df.columns:
                col_str = str(col)
                if '产品代码' in col_str or '资产代码' in col_str:
                    product_key = str(df[col].iloc[0])
                if '产品名称' in col_str or '资产名称' in col_str:
                    product_name = str(df[col].iloc[0])

            if product_key is None:
                for part in filename.split('_'):
                    if len(part) >= 6 and part.isalnum() and not part.isalpha():
                        product_key = part
                        break

            if product_key is None:
                product_key = filename

            date_val = None
            date_str = str(df[date_col].iloc[0])
            if re.match(r'\d{8}', date_str):
                date_val = pd.to_datetime(date_str).date()
            elif re.match(r'\d{4}-\d{2}-\d{2}', date_str):
                date_val = pd.to_datetime(date_str).date()
            elif '年' in date_str:
                date_str = date_str.replace('年', '-').replace('月', '-').replace('日', '')
                try:
                    date_val = pd.to_datetime(date_str).date()
                except Exception:
                    pass

            nav_val = pd.to_numeric(df[nav_col].iloc[0], errors='coerce')
            if pd.isna(nav_val):
                continue

            product_data[product_key]['dates'].append(date_val)
            product_data[product_key]['navs'].append(nav_val)
            if product_name:
                product_data[product_key]['name'] = product_name

        result = {}
        for key, data in product_data.items():
            if len(data['dates']) > 1:
                sorted_pairs = sorted(zip(data['dates'], data['navs']))
                result[key] = {
                    'dates': [p[0] for p in sorted_pairs],
                    'navs': [p[1] for p in sorted_pairs],
                    'name': data['name'] or key
                }

        return result

    def calculate_metrics(self, dates, nav_values, product_name):
        """计算各项指标（复刻旧 calculate_metrics）"""
        df = pd.DataFrame({'日期': dates, '累计净值': nav_values})
        df = df.dropna(subset=['日期', '累计净值'])
        df['日期'] = pd.to_datetime(df['日期'])
        df = df.sort_values('日期').reset_index(drop=True)
        df['累计净值'] = pd.to_numeric(df['累计净值'], errors='coerce')
        df = df.dropna(subset=['累计净值'])

        if len(df) < 2:
            return None, df

        df['日收益率'] = df['累计净值'].pct_change().fillna(0)

        df['年份'] = df['日期'].dt.year
        annual_ret_dict = {}
        for year, group in df.groupby('年份'):
            if len(group) > 1:
                annual_ret_dict[year] = group['累计净值'].iloc[-1] / group['累计净值'].iloc[0] - 1
            elif len(group) == 1:
                annual_ret_dict[year] = 0

        cum_nav = df['累计净值'].values
        running_max = np.maximum.accumulate(cum_nav)
        drawdown = (cum_nav - running_max) / running_max
        max_drawdown = drawdown.min()

        daily_ret = df['日收益率'].dropna()
        annual_vol = daily_ret.std() * np.sqrt(TRADING_DAYS)

        start_nav = df['累计净值'].iloc[0]
        end_nav = df['累计净值'].iloc[-1]
        total_return = end_nav / start_nav - 1
        total_days = (df['日期'].iloc[-1] - df['日期'].iloc[0]).days

        if total_days > 0:
            annualized_return = (1 + total_return) ** (365 / total_days) - 1
        else:
            annualized_return = 0

        if max_drawdown != 0:
            calmar = annualized_return / abs(max_drawdown)
        else:
            calmar = np.nan

        if annual_vol != 0:
            avg_daily_ret = daily_ret.mean()
            excess_annual_ret = avg_daily_ret * TRADING_DAYS - RISK_FREE_RATE
            sharpe = excess_annual_ret / annual_vol
        else:
            sharpe = np.nan

        df_monthly = df.set_index('日期').resample('ME').last()
        df_monthly['月收益率'] = df_monthly['累计净值'].pct_change().fillna(0)
        max_consecutive_down = 0
        current = 0
        for ret in df_monthly['月收益率']:
            if ret < 0:
                current += 1
                max_consecutive_down = max(max_consecutive_down, current)
            else:
                current = 0

        metrics = {
            '产品代码': product_name,
            '起始日期': df['日期'].iloc[0].strftime('%Y-%m-%d'),
            '截止日期': df['日期'].iloc[-1].strftime('%Y-%m-%d'),
            '数据天数': total_days,
            '最大回撤': max_drawdown,
            '年化波动率': annual_vol,
            '卡玛比率': calmar,
            '夏普比率': sharpe,
            '最常连续下跌月度': max_consecutive_down,
            '年化收益率': annualized_return,
            '总收益率': total_return,
        }
        for year, ret in annual_ret_dict.items():
            metrics[f'{year}年收益'] = ret

        return metrics, df

    def plot_nav_curve(self, df, product_name, output_dir):
        """绘制净值曲线（复刻旧 plot_nav_curve）"""
        fig, ax = plt.subplots(figsize=(12, 6))
        ax.plot(df['日期'], df['累计净值'], linewidth=1.5, color='blue')
        ax.set_title(f'{product_name} - 累计净值曲线', fontsize=14)
        ax.set_xlabel('日期')
        ax.set_ylabel('累计单位净值')
        ax.grid(alpha=0.3)

        safe_name = "".join(c for c in str(product_name) if c.isalnum() or c in (' ', '-', '_')).strip()
        img_path = os.path.join(output_dir, f'{safe_name}_净值曲线.png')
        plt.tight_layout()
        plt.savefig(img_path, dpi=150)
        plt.close()
        return img_path

    def analyze_single_file(self, file_path, output_dir):
        """分析单个文件（可能含有多天数据，复刻旧 analyze_single_file）"""
        filename = os.path.basename(file_path)

        try:
            if filename.endswith('.csv'):
                df = pd.read_csv(file_path, encoding='utf-8-sig')
            else:
                df = pd.read_excel(file_path)
        except Exception:
            return None

        date_col, nav_col = self.find_columns(df)
        if date_col is None or nav_col is None:
            return None

        product_name = None
        for col in df.columns:
            if '产品名称' in str(col) or '资产名称' in str(col):
                product_name = str(df[col].iloc[0])
                break
        if product_name is None:
            product_name = filename.replace('.xlsx', '').replace('.xls', '').replace('.csv', '')

        dates = df[date_col]
        navs = df[nav_col]

        metrics, df_clean = self.calculate_metrics(dates, navs, product_name)
        if df_clean is None or len(df_clean) < 2:
            return None

        img_path = self.plot_nav_curve(df_clean, product_name, output_dir)
        metrics['净值曲线图'] = img_path

        return metrics

    def analyze_directory(self, input_dir, output_dir):
        """分析目录下所有净值表，返回指标字典列表（复刻旧 analyze_directory 的计算与绘图）"""
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        product_data = self.aggregate_nav_files_by_product(input_dir)

        all_metrics = []

        if product_data:
            for product_key, data in product_data.items():
                metrics, df_clean = self.calculate_metrics(data['dates'], data['navs'], data['name'])
                if metrics is None or df_clean is None or len(df_clean) < 2:
                    continue

                img_path = self.plot_nav_curve(df_clean, data['name'], output_dir)
                metrics['净值曲线图'] = img_path
                all_metrics.append(metrics)
        else:
            extensions = ('.xlsx', '.xls', '.csv')
            files = []
            for ext in extensions:
                files.extend(Path(input_dir).glob(f'*{ext}'))
                files.extend(Path(input_dir).glob(f'*{ext.upper()}'))

            for file_path in files:
                metrics = self.analyze_single_file(str(file_path), output_dir)
                if metrics:
                    all_metrics.append(metrics)

        return all_metrics
