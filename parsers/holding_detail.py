from pathlib import Path
import pandas as pd
from .base import BaseParser
from core.models import HoldingDetail, HoldingType
from core.rules import extract_code_name_from_filename


class HoldingDetailParser(BaseParser):
    """持仓明细解析器。

    逐字节复刻旧版 run_holding.py 的提取逻辑，确保收敛后输出与旧脚本完全一致：
    - 遍历所有工作表（优先 '估值表明细表'），df 以 header=0 读取
    - 固定列索引 0..10（科目代码/科目名称/数量/.../停牌信息）
    - 父行（科目名称含'成本'且有科目代码）→ 其子行（科目代码以父行代码开头）为持仓
    - 公募基金父行判定：含'基金'且不含'资产管理'/'私募'
    - 原始数值（含缺失 None）原样保留，供 reporter 精确还原
    """
    PARENT_KW = "成本"
    CHILD_MAP = {"管理计划": HoldingType.BROKER_PLAN, "私募": HoldingType.PRIVATE_FUND}

    COL = {
        '科目代码': 0, '科目名称': 1, '数量': 2, '单位成本': 3,
        '成本': 4, '成本占净值%': 5, '市价': 6, '市值': 7,
        '市值占净值%': 8, '估值增值': 9, '停牌信息': 10
    }

    def parse(self, file_path: Path) -> list:
        self._current_file = file_path
        sheets = self._read(file_path)
        return self._do_parse(sheets)

    def _read(self, file_path: Path):
        xl = pd.ExcelFile(file_path)
        sheets = ['估值表明细表'] if '估值表明细表' in xl.sheet_names else xl.sheet_names
        out = []
        for s in sheets:
            df = pd.read_excel(file_path, sheet_name=s, header=0)
            if df.shape[1] < 11:
                continue
            out.append((s, df))
        return out

    def _do_parse(self, sheets) -> list:
        results = []
        for sheet_name, df in sheets:
            results.extend(self._parse_sheet(df, sheet_name))
        return results

    def _parse_sheet(self, df, sheet_name):
        holdings = []
        file_stem = Path(self._file_name).stem
        project_code, project_name = extract_code_name_from_filename(file_stem)

        cost_rows = []
        for idx, row in df.iterrows():
            name = str(row.iloc[self.COL['科目名称']]).strip() if pd.notna(row.iloc[self.COL['科目名称']]) else ""
            code = str(row.iloc[self.COL['科目代码']]).strip() if pd.notna(row.iloc[self.COL['科目代码']]) else ""
            if self.PARENT_KW in name and code:
                cost_rows.append({'idx': idx, 'code': code, 'name': name.strip()})

        for cost in cost_rows:
            cost_code = cost['code']
            parent_name = cost['name']
            # 公募基金父行判定：含'基金'且不含'资产管理'/'私募'
            if '私募' in parent_name or '资产管理' in parent_name:
                parent_is_public = False
            else:
                parent_is_public = '基金' in parent_name
            for search_idx, row in df.iterrows():
                if search_idx == cost['idx']:
                    continue
                subj_code = str(row.iloc[self.COL['科目代码']]).strip() if pd.notna(row.iloc[self.COL['科目代码']]) else ""
                if not subj_code.startswith(cost_code):
                    continue
                subj_name = str(row.iloc[self.COL['科目名称']]).strip() if pd.notna(row.iloc[self.COL['科目名称']]) else ""
                if parent_is_public:
                    # 跳过小计/公允价值变动等非具体基金行
                    if any(k in subj_name for k in ('成本', '公允价值变动', '合计')):
                        continue
                    found = '公募基金'
                else:
                    found = None
                    for kw in self.CHILD_MAP:
                        if kw in subj_name:
                            found = kw
                            break
                if found:
                    mv_raw = row.iloc[self.COL['市值']] if pd.notna(row.iloc[self.COL['市值']]) else None
                    pct_raw = row.iloc[self.COL['市值占净值%']] if pd.notna(row.iloc[self.COL['市值占净值%']]) else None
                    holdings.append(HoldingDetail(
                        project_code=project_code,
                        project_name=project_name,
                        target_name=subj_name,
                        account_code=subj_code,
                        holding_type=HoldingType(found),
                        market_value=self._safe_decimal(mv_raw),
                        nav_pct=self._safe_decimal(pct_raw),
                        source_row=search_idx + 2,
                        table_name=file_stem,
                        sheet_name=sheet_name,
                        cost_row=cost['idx'] + 2,
                        cost_code=cost_code,
                        cost_name=cost['name'],
                        rel_pos='下方' if search_idx > cost['idx'] else '上方',
                        match_keyword=found,
                        quantity=row.iloc[self.COL['数量']] if pd.notna(row.iloc[self.COL['数量']]) else None,
                        unit_cost=row.iloc[self.COL['单位成本']] if pd.notna(row.iloc[self.COL['单位成本']]) else None,
                        cost=row.iloc[self.COL['成本']] if pd.notna(row.iloc[self.COL['成本']]) else None,
                        cost_nav_pct=row.iloc[self.COL['成本占净值%']] if pd.notna(row.iloc[self.COL['成本占净值%']]) else None,
                        market_price=row.iloc[self.COL['市价']] if pd.notna(row.iloc[self.COL['市价']]) else None,
                        valuation_add=row.iloc[self.COL['估值增值']] if pd.notna(row.iloc[self.COL['估值增值']]) else None,
                        halt_info=row.iloc[self.COL['停牌信息']] if pd.notna(row.iloc[self.COL['停牌信息']]) else None,
                        mv_raw=mv_raw,
                        pct_raw=pct_raw,
                    ))
        return holdings
