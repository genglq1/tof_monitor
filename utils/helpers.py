from pathlib import Path
from decimal import Decimal, InvalidOperation
from datetime import date
import pandas as pd
import re

def safe_decimal(value) -> Decimal:
    try:
        return Decimal(str(value)) if pd.notna(value) else Decimal(0)
    except (InvalidOperation, ValueError):
        return Decimal(0)

def extract_project_info(filename: str):
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