# -*- coding: utf-8 -*-
"""
持仓明细相关的通用规则与文件名解析。
从旧版 run_holding.py 收口而来，供 core 框架各模块统一复用，避免规则重复/分叉。
"""
import re

# 估值表文件名前缀（用于从文件名提取项目代码与名称）
_FILE_PREFIXES = ['估值表_', '证券投资基金估值表_', '资产估值表_', '基金估值表_']


def extract_code_name_from_filename(stem: str):
    """从文件名 stem 提取 (项目代码, 项目名称)。

    逻辑与旧版 run_holding.extract_code_name_from_filename 完全一致：
    - 去除已知前缀
    - 形如 ``ZY0MXT_中原财富-精诚稳健型2号集合资金信托计划_20260630``
      取中间 5~8 位大写字母数字串为代码，其后到日期前的部分为名称
    """
    s = stem
    for prefix in _FILE_PREFIXES:
        if s.startswith(prefix):
            s = s[len(prefix):]
            break
    parts = s.split('_')
    code = None
    name_parts = []
    for i, p in enumerate(parts):
        if re.match(r'^[A-Z0-9]{5,8}$', p):
            code = p
            name_parts = parts[i + 1:-1] if len(parts) > i + 2 else parts[i + 1:]
            break
    if code is None:
        code = parts[0] if parts else s[:6]
        name_parts = parts[1:-1] if len(parts) > 2 else parts[1:]
    project_name = '_'.join(name_parts) if name_parts else s
    if project_name and re.search(r'_\d{8}$', project_name):
        project_name = '_'.join(project_name.split('_')[:-1])
    return code, project_name


def extract_short_name(project_name: str) -> str:
    """从项目名称提取投资标的简称（标准表所需）。

    规则：取 '-' 分隔的第一段；若无 '-' 则取前 8 字符。
    与旧版 run_holding._extract_short_name 完全一致。
    """
    if not project_name:
        return ""
    parts = str(project_name).split('-')
    if len(parts) >= 2:
        return parts[0].strip()
    return project_name[:8] if len(project_name) > 8 else project_name


# ================================================================
# 产品类型识别规则（从 manager_pipeline.PRODUCT_TYPE_RULES 收口）
# 所有模块统一从此处 import，避免规则分叉。
# ================================================================
PRODUCT_TYPE_RULES = [
    ("资管计划", ["资产管理计划", "集合资产管理", "单一资产管理", "专项资产管理"]),
    ("私募",   ["私募证券", "私募基金", "私募投资"]),
    ("公募",   ["ETF", "LOF", "QDII", "FOF",
                "货币市场基金", "债券型证券投资基金", "股票型证券投资基金",
                "混合型证券投资基金", "指数型证券投资基金", "指数增强"]),
]


def detect_product_type(name: str) -> str:
    """从产品名称识别产品类型（资管计划/私募/公募/其他）。

    与旧版 manager_pipeline.detect_product_type 完全一致。
    """
    if not isinstance(name, str) or not name.strip():
        return "其他"
    s = name.strip()
    for ptype, kws in PRODUCT_TYPE_RULES:
        if any(kw in s for kw in kws):
            return ptype
    return "其他"
