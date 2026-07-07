# -*- coding: utf-8 -*-
"""
持仓明细收敛的黄金 diff 测试。
确保 core 框架（parsers.holding_detail + reporters.holding_reporter）的输出
与旧版 run_holding.py 完全一致（逐行逐列精确一致）。
"""
import warnings
warnings.filterwarnings("ignore")

from pathlib import Path
import shutil
import tempfile

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from parsers.holding_detail import HoldingDetailParser
from reporters.holding_reporter import HoldingReporter
from core.models import HoldingType
from parsers.valuation_stats import ValuationStatsParser
from reporters.valuation_reporter import ValuationReporter
from core.manager import ManagerFiller
from parsers.penetration import PenetrationParser
from reporters.penetration_reporter import PenetrationReporter
from core.nav_analyzer import NavAnalyzer
from reporters.nav_reporter import NavReporter
import glob

BASE = Path(__file__).parent.parent
SAMPLES = BASE / "tests" / "fixtures" / "samples"
EXPECTED = BASE / "tests" / "fixtures" / "expected"
MANAGER_MAPPING = BASE / "tests" / "fixtures" / "manager" / "MANAGER_FULLNAME.xlsx"
PEN = BASE / "tests" / "fixtures" / "penetration"
NAV = BASE / "tests" / "fixtures" / "nav"


def _core_outputs(sample_dir):
    parser = HoldingDetailParser()
    reporter = HoldingReporter()
    holdings = []
    for f in sorted(sample_dir.glob("*估值表*.xls*")):
        holdings.extend(parser.parse(f))
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        full = reporter.write_full(holdings, td / "full.xlsx")
        std = reporter.write_std(holdings, td / "std.xlsx")
        new_full = pd.read_excel(full)
        new_std = pd.read_excel(std)
    return new_full, new_std


def test_holding_full_golden_diff():
    """完整表：与旧版 run_holding 输出精确一致。"""
    exp = pd.read_excel(EXPECTED / "信托计划持仓_完整.xlsx")
    new_full, _ = _core_outputs(SAMPLES)
    assert_frame_equal(new_full, exp, check_exact=True, check_like=True, check_dtype=False)


def test_holding_std_golden_diff():
    """标准表（含简称）：与旧版 run_holding 输出精确一致。"""
    exp = pd.read_excel(EXPECTED / "信托计划持仓_标准.xlsx")
    _, new_std = _core_outputs(SAMPLES)
    assert_frame_equal(new_std, exp, check_exact=True, check_like=True, check_dtype=False)


def test_public_fund_sample_count():
    """公募样本 ZY0MXT：正确识别 17 条公募基金。"""
    parser = HoldingDetailParser()
    f = SAMPLES / "估值表_ZY0MXT_中原财富-精诚稳健型2号集合资金信托计划_20260630.xls"
    hs = parser.parse(f)
    pub = [h for h in hs if h.holding_type == HoldingType.PUBLIC_FUND]
    assert len(pub) == 17, f"ZY0MXT 公募应为 17，实际 {len(pub)}"


def test_no_misclassified_asset_mgmt_product():
    """私募样本 ZY0LD7：'基金资产管理产品成本' 父行下的子行不得误判为公募。"""
    parser = HoldingDetailParser()
    f = SAMPLES / "估值表_ZY0LD7_中原信托-睿选30号-同温层集合资金信托计划_20260630.xls"
    hs = parser.parse(f)
    bad = [h for h in hs
           if '基金资产管理产品' in h.cost_name and h.holding_type == HoldingType.PUBLIC_FUND]
    assert not bad, f"基金资产管理产品成本 被误判为公募: {[h.target_name for h in bad]}"


def test_valuation_stats_golden_diff():
    """估值统计表：与旧版 run_valuation 输出精确一致。"""
    exp = pd.read_excel(EXPECTED / "信托产品估值统计结果.xlsx", sheet_name="统计结果")
    parser = ValuationStatsParser()
    stats, _ = parser.parse(SAMPLES)
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "stats.xlsx"
        ValuationReporter().write_stats(stats, out)
        new = pd.read_excel(out, sheet_name="统计结果")
    assert_frame_equal(new, exp, check_exact=True, check_like=True, check_dtype=False)


def test_manager_fill_golden_diff():
    """管理人回填：完整表 + 产品类型/管理人名称，与旧版 manager_pipeline 输出精确一致。"""
    full = pd.read_excel(EXPECTED / "信托计划持仓_完整.xlsx")
    exp = pd.read_excel(EXPECTED / "信托计划持仓_完整_管理人.xlsx")
    new = ManagerFiller().fill_frame(full.copy(), MANAGER_MAPPING)
    # 经 Excel 往返，模拟实际落盘（空字符串在 Excel 中读回为 NaN，与基线一致）
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "m.xlsx"
        new.to_excel(p, index=False)
        new = pd.read_excel(p)
    assert_frame_equal(new, exp, check_exact=True, check_like=True, check_dtype=False)


def test_penetration_golden_diff():
    """穿透报告：与旧版 run_penetration 输出精确一致。"""
    baseline_files = glob.glob(str(EXPECTED / "*穿透报告*.xlsx"))
    assert baseline_files, "基线穿透报告缺失"
    exp = pd.read_excel(baseline_files[0], sheet_name="穿透固收&权益")

    parser = PenetrationParser()
    holding_std = PEN / "信托计划持仓_标准.xlsx"
    valuation_stats = PEN / "信托产品估值统计结果.xlsx"
    search_dirs = [PEN / "trust"]
    res = parser.generate("ZY0TST", "20260630", holding_std, valuation_stats, search_dirs)
    assert res.success, "穿透生成失败"
    with tempfile.TemporaryDirectory() as td:
        out = PenetrationReporter().write_report(res, Path(td))
        new = pd.read_excel(out, sheet_name="穿透固收&权益")
    assert_frame_equal(new, exp, check_exact=True, check_like=True, check_dtype=False)


def test_nav_golden_diff():
    """净值分析：与旧版 analyze_nav 输出精确一致（净值曲线图列含环境路径，跳过）。"""
    baseline = pd.read_excel(EXPECTED / "净值分析结果.xlsx")
    assert len(baseline) > 0, "基线净值分析结果缺失"

    analyzer = NavAnalyzer()
    with tempfile.TemporaryDirectory() as td:
        metrics = analyzer.analyze_directory(str(NAV), td)
        assert metrics, "净值分析未产出任何指标"
        out = NavReporter().write_report(metrics, Path(td))
        new = pd.read_excel(out)

    # 净值曲线图列含输出目录绝对路径，环境相关，不参与精确比较
    drop = [c for c in baseline.columns if c == "净值曲线图"]
    base_cmp = baseline.drop(columns=drop).reset_index(drop=True)
    new_cmp = new.drop(columns=drop).reset_index(drop=True)
    assert_frame_equal(new_cmp, base_cmp, check_exact=True, check_like=True, check_dtype=False)


if __name__ == "__main__":
    test_holding_full_golden_diff()
    test_holding_std_golden_diff()
    test_public_fund_sample_count()
    test_no_misclassified_asset_mgmt_product()
    test_valuation_stats_golden_diff()
    test_manager_fill_golden_diff()
    test_penetration_golden_diff()
    test_nav_golden_diff()
    print("全部收敛测试通过")
