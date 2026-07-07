import re
import shutil
from pathlib import Path
from typing import List
from loguru import logger
from core.models import ValuationFile, HoldingDetail

class FileStore:
    def __init__(self, archive_base: Path):
        self.archive_base = archive_base
        self.archive_base.mkdir(parents=True, exist_ok=True)

    def organize_from_classification(self, holdings: List[HoldingDetail], source_files: List[ValuationFile],
                                     dest_root: Path):
        code_files = {}
        for vf in source_files:
            if vf.level == "trust":
                code = vf.project_code
                code_files.setdefault(code, []).append(vf.file_path)
        for h in holdings:
            trust_code = h.project_code
            trust_files = code_files.get(trust_code, [])
            if not trust_files:
                continue
            safe_name = self._clean_name(f"{trust_code}_{h.target_name}")
            dest_folder = dest_root / safe_name
            dest_folder.mkdir(parents=True, exist_ok=True)
            for src_path in trust_files:
                src = Path(src_path)
                # 确保源文件存在且可访问
                if not src.exists() or not src.is_file():
                    logger.warning(f"源文件不存在或不是文件，跳过: {src_path}")
                    continue
                try:
                    dest_folder.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dest_folder / src.name)
                except Exception as e:
                    logger.error(f"复制文件失败: {src_path} -> {dest_folder} : {e}")

    def _clean_name(self, name: str) -> str:
        return re.sub(r'[<>:"/\\|?*]', '_', name)[:100]