import warnings
warnings.filterwarnings("ignore", message="Workbook contains no default style")
warnings.filterwarnings("ignore", message="OLE2 stream")

from abc import ABC, abstractmethod
from decimal import Decimal, InvalidOperation
from typing import List, Any, Tuple, Dict
from pathlib import Path
from datetime import date
import pandas as pd


class BaseParser(ABC):
    def parse(self, file_path: Path) -> List[Any]:
        self._current_file = file_path
        df = self._read(file_path)
        self._validate(df, file_path)
        return self._do_parse(df)

    def _read(self, file_path: Path) -> pd.DataFrame:
        if not file_path.is_file():
            raise ValueError(f"Not a file: {file_path}")
        return pd.read_excel(file_path, header=None)

    def _validate(self, df: pd.DataFrame, file_path: Path = None):
        if df.empty:
            raise ValueError(f"Empty file: {file_path or 'unknown'}")

    def _safe_decimal(self, value) -> Decimal:
        try:
            return Decimal(str(value)) if pd.notna(value) else Decimal(0)
        except (InvalidOperation, ValueError):
            return Decimal(0)

    def _extract_project_info(self, filename: str) -> Tuple[str, str, date]:
        stem = Path(filename).stem
        for prefix in ['估值表_', '证券投资基金估值表_']:
            if stem.startswith(prefix):
                stem = stem[len(prefix):]
                break
        parts = stem.split('_')
        code = parts[0] if parts else "UNKNOWN"
        vdate = None
        for p in reversed(parts):
            if p.isdigit() and len(p) == 8:
                vdate = pd.to_datetime(p).date()
                break
        name = '_'.join(parts[1:-1]) if len(parts) > 2 else stem
        return code, name, vdate

    def _locate_header(self, df: pd.DataFrame, keywords: List[str] = None) -> Tuple[int, Dict[str, int]]:
        keywords = keywords or ['科目名称', '科目代码']
        for i in range(min(15, len(df))):
            row = df.iloc[i].astype(str)
            if any(kw in row.values for kw in keywords):
                col_map = {}
                for j, val in enumerate(row):
                    if '市值占净值' in val or '市值占比' in val:
                        col_map['市值占净值%'] = j
                    elif '市值' in val:
                        col_map['市值'] = j
                return i, col_map
        return 0, {}

    @abstractmethod
    def _do_parse(self, df: pd.DataFrame) -> List[Any]:
        ...

    @property
    def _file_name(self) -> str:
        return self._current_file.name if self._current_file else ""