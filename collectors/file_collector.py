from pathlib import Path
from typing import List
from datetime import date
from core.models import ValuationFile
from utils.helpers import extract_project_info


class FileCollector:
    def __init__(self, root_dir: Path, pattern: str = "*.xls*"):
        self.root_dir = root_dir
        self.pattern = pattern

    def collect(self) -> List[ValuationFile]:
        """递归收集目录下所有 Excel 文件"""
        files = []
        if not self.root_dir.exists():
            return files

        for f in self.root_dir.rglob(self.pattern):
            # 如果是目录（邮件文件夹），在其内部查找 Excel 文件
            if f.is_dir():
                for inner in f.rglob(self.pattern):
                    if self._should_include(inner):
                        files.append(self._make_valuation_file(inner))
                continue
            # 普通文件
            if self._should_include(f):
                files.append(self._make_valuation_file(f))

        # 对文件夹路径特殊处理：如果收集到的是文件夹（邮件收集器返回的），
        # 展开为其内部的 Excel 文件
        expanded = []
        for vf in files:
            p = Path(vf.file_path)
            if p.is_dir():
                for inner in p.rglob(self.pattern):
                    if self._should_include(inner):
                        expanded.append(self._make_valuation_file(inner))
            else:
                expanded.append(vf)
        return expanded

    def _should_include(self, f: Path) -> bool:
        """检查文件是否应该被包含"""
        if not f.is_file():
            return False
        if f.name.startswith('_') or f.name.startswith('.'):
            return False
        # 排除提示函等非估值表文件
        name_lower = f.name.lower()
        if '提示函' in f.name:
            return False
        return True

    def _make_valuation_file(self, f: Path) -> ValuationFile:
        """从文件路径创建 ValuationFile"""
        code, name, vdate = extract_project_info(f.name)
        if vdate is None:
            vdate = date.today()
        return ValuationFile(
            file_path=str(f),
            project_code=code,
            project_name=name,
            file_date=vdate,
            level="trust"
        )
