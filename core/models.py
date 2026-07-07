from dataclasses import dataclass, field
from decimal import Decimal
from datetime import date
from enum import Enum
from typing import List, Optional

class HoldingType(Enum):
    PRIVATE_FUND = "私募"
    BROKER_PLAN = "管理计划"
    PUBLIC_FUND = "公募基金"
    TRUST_PLAN = "信托计划"
    OTHER = "其他"

@dataclass
class AssetItem:
    account_code: str = ""
    account_name: str = ""
    market_value: Decimal = Decimal(0)
    nav_pct: Decimal = Decimal(0)

@dataclass
class AssetOverview:
    project_code: str
    project_name: str
    valuation_date: date
    bank_deposit: AssetItem = field(default_factory=AssetItem)
    guarantee_fund: AssetItem = field(default_factory=AssetItem)
    securities_total: AssetItem = field(default_factory=AssetItem)
    paid_in_trust: AssetItem = field(default_factory=AssetItem)
    liabilities_total: AssetItem = field(default_factory=AssetItem)
    assets_total: AssetItem = field(default_factory=AssetItem)

@dataclass
class HoldingDetail:
    project_code: str
    project_name: str
    target_name: str
    account_code: str
    holding_type: HoldingType
    market_value: Decimal = Decimal(0)
    nav_pct: Decimal = Decimal(0)
    source_row: int = 0
    short_name: str = ""
    # —— 完整工作表（下游 classify/管理人回填/穿透 强依赖）所需字段 ——
    table_name: str = ""           # 表格名称（文件名 stem）
    sheet_name: str = ""           # 工作表名称
    cost_row: int = 0              # 成本科目行号（1-based，含表头）
    cost_code: str = ""            # 成本科目代码
    cost_name: str = ""            # 成本科目名称
    rel_pos: str = ""              # 目标相对位置：上方/下方
    match_keyword: str = ""        # 匹配关键词（公募基金/管理计划/私募）
    quantity: object = None        # 数量
    unit_cost: object = None       # 单位成本
    cost: object = None            # 成本
    cost_nav_pct: object = None    # 成本占净值%
    market_price: object = None    # 市价
    valuation_add: object = None   # 估值增值
    halt_info: object = None       # 停牌信息
    # 原始市值/占比（保留 None 以精确还原 run_holding 输出；market_value/nav_pct 为 Decimal 供管道计算）
    mv_raw: object = None
    pct_raw: object = None

@dataclass
class ValuationFile:
    file_path: str
    project_code: str = ""
    project_name: str = ""
    file_date: date = field(default_factory=date.today)
    level: str = "trust"  # 'trust' or 'underlying'