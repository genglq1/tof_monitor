from pathlib import Path
from decimal import Decimal
import pandas as pd
from .base import BaseParser
from core.models import AssetOverview, AssetItem

class AssetOverviewParser(BaseParser):
    METRICS = [
        "银行存款",
        "信托保障基金",
        "证券投资合计",
        "实收信托",
        "负债类合计",
        "资产类合计",
    ]

    def _do_parse(self, df: pd.DataFrame):
        code, name, vdate = self._extract_project_info(self._file_name)
        if self._is_empty(df):
            return []

        header_row, col_map = self._locate_header(df)
        data = {}
        for metric in self.METRICS:
            found = None
            for i in range(header_row + 1, len(df)):
                row_str = ' '.join(df.iloc[i].astype(str).values)
                if metric in row_str:
                    found = i
                    break
            if found is None:
                data[metric] = AssetItem(account_name=metric)
                continue
            row = df.iloc[found]
            mv_val = Decimal(0)
            pct_val = Decimal(0)
            if '市值' in col_map:
                mv_val = self._safe_decimal(row.iloc[col_map['市值']])
            else:
                nums = [x for x in row if isinstance(x, (int, float)) and not pd.isna(x)]
                if len(nums) >= 2:
                    mv_val = self._safe_decimal(nums[-2])
            if '市值占净值%' in col_map:
                pct_val = self._safe_decimal(row.iloc[col_map['市值占净值%']])
            else:
                nums = [x for x in row if isinstance(x, (int, float)) and not pd.isna(x)]
                if len(nums) >= 1:
                    pct_val = self._safe_decimal(nums[-1])
            data[metric] = AssetItem(account_name=metric, market_value=mv_val, nav_pct=pct_val)

        overview = AssetOverview(
            project_code=code,
            project_name=name,
            valuation_date=vdate,
            bank_deposit=data.get("银行存款", AssetItem()),
            guarantee_fund=data.get("信托保障基金", AssetItem()),
            securities_total=data.get("证券投资合计", AssetItem()),
            paid_in_trust=data.get("实收信托", AssetItem()),
            liabilities_total=data.get("负债类合计", AssetItem()),
            assets_total=data.get("资产类合计", AssetItem()),
        )
        return [overview]

    def _is_empty(self, df: pd.DataFrame) -> bool:
        if df.empty:
            return True
        for i in range(min(10, len(df))):
            if '科目代码' in str(df.iloc[i].values) or '科目名称' in str(df.iloc[i].values):
                return False
        return True