from pathlib import Path
from datetime import date
from typing import List, Optional
from loguru import logger

from core.models import (
    ValuationFile, AssetOverview, HoldingDetail,
)
from core.registry import registry

class Pipeline:
    def __init__(self, trust_files: List[ValuationFile],
                 underlying_files: List[ValuationFile] = None,
                 output_dir: Path = Path("output")):
        self.trust_files = trust_files
        self.underlying_files = underlying_files or []
        self.output_dir = output_dir
        self.errors = []

    def run(self) -> dict:
        overviews = self._parse_overviews()
        holdings = self._parse_holdings()
        return {
            "overviews": overviews,
            "holdings": holdings,
            "errors": self.errors
        }

    def _parse_overviews(self) -> List[AssetOverview]:
        parser = registry.get("asset_overview")
        results = []
        total = len(self.trust_files)
        for idx, vf in enumerate(self.trust_files):
            if idx > 0 and idx % 20 == 0:
                logger.info(f"解析资产总览进度: {idx}/{total}")
            try:
                results.extend(parser.parse(Path(vf.file_path)))
            except Exception as e:
                logger.error(f"解析资产总览失败: {vf.file_path} - {e}")
                self.errors.append(f"资产总览失败: {vf.file_path}")
        if total > 0:
            logger.info(f"解析资产总览完成: {len(results)} 条记录")
        return results

    def _parse_holdings(self) -> List[HoldingDetail]:
        parser = registry.get("holding_detail")
        results = []
        total = len(self.trust_files)
        for idx, vf in enumerate(self.trust_files):
            if idx > 0 and idx % 20 == 0:
                logger.info(f"解析持仓明细进度: {idx}/{total}")
            try:
                results.extend(parser.parse(Path(vf.file_path)))
            except Exception as e:
                logger.error(f"解析持仓明细失败: {vf.file_path} - {e}")
                self.errors.append(f"持仓明细失败: {vf.file_path}")
        if total > 0:
            logger.info(f"解析持仓明细完成: {len(results)} 条记录")
        return results
