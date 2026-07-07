"""
文件分类器 - 按投资标的分类文件到独立文件夹
功能：
1. 读取持仓Excel，获取项目代码→投资标的映射
2. 扫描原始邮件目录，按文件名关键词匹配
3. 日期范围过滤
4. 复制文件到对应投资标的文件夹
5. 生成"是否找到"标记列
6. 生成复制记录和分类统计报告
"""

import re
import shutil
import pandas as pd
from pathlib import Path
from datetime import datetime
from typing import Dict, Set, List
from loguru import logger


class FileClassifier:
    def __init__(
        self,
        project_file: Path,
        source_dir: Path,
        output_base: Path,
        filename_keyword: str = "估值表",
        start_date: str = "",
        end_date: str = "",
        short_name_col: str = None
    ):
        self.project_file = project_file
        self.source_dir = source_dir
        self.output_base = output_base
        self.filename_keyword = filename_keyword
        self.start_date = self._parse_date(start_date)
        self.end_date = self._parse_date(end_date)
        self.short_name_col = short_name_col

        self.code_to_info: Dict[str, tuple] = {}  # 科目代码末位 -> (投资标的, 项目名称, 项目代码)
        self.target_folders: Dict[str, tuple] = {}  # 投资标的 -> (项目代码, 文件夹路径)
        self.all_targets: Set[str] = set()  # 所有投资标的
        self.copied_records: List[dict] = []
        self.newly_copied_files: List[Path] = []  # 本次运行新复制的文件路径
        self.stats = {
            'total_emails': 0,
            'total_files': 0,
            'skipped_by_keyword': 0,
            'skipped_by_date': 0,
            'unmatched_keyword': 0,
            'unmatched_target': 0,
            'copied_files': 0,
        }

    def _parse_date(self, date_str: str):
        if not date_str:
            return None
        try:
            if re.fullmatch(r'\d{8}', date_str):
                return datetime.strptime(date_str, "%Y%m%d").date()
            return datetime.strptime(date_str, "%Y-%m-%d").date()
        except:
            return None

    def _safe_str(self, value) -> str:
        return "" if pd.isna(value) else str(value).strip()

    def _clean_filename(self, name: str) -> str:
        if not name:
            return "未命名"
        name = str(name)
        # 移除 IMAP 协议响应格式前缀
        m = re.match(r'^(\d+)\s*\(UID\s+\d+\s+RFC822\s+\{\d+\}_\s*(.*)', name, re.DOTALL)
        if m:
            name = m.group(2)
        illegal = r'[\\/*?:"<>|]'
        for ch in illegal:
            name = name.replace(ch, '_')
        name = name.strip()
        if len(name) > 100:
            base, ext = Path(name).stem, Path(name).suffix
            name = base[:100 - len(ext)] + ext
        return name if name not in ('', '_') else "未命名"

    def load_project_info(self) -> bool:
        """加载项目信息，构建关键词→投资标的映射"""
        logger.info("[步骤] 加载项目信息...")
        if not self.project_file.exists():
            logger.error(f"文件不存在: {self.project_file}")
            return False

        df = pd.read_excel(self.project_file, header=0)
        logger.info(f"读取成功，共 {len(df)} 行，列名: {list(df.columns)}")

        if len(df.columns) < 5:
            logger.error("Excel列数不足")
            return False

        cols = list(df.columns)

        code_col = cols[0]        # 项目代码
        target_col = cols[5]      # 投资标的
        name_col = cols[1]        # 项目名称
        account_col = cols[4]     # 科目代码

        # 科目代码末位 -> [(投资标的, 项目名称, 项目代码), ...]
        self.code_to_targets: Dict[str, List[tuple]] = {}
        # 项目名称 -> set(投资标的)
        self.name_to_targets: Dict[str, Set[str]] = {}
        # 投资标的 -> [(项目代码, 项目名称), ...]（同一投资标的可能出现在多个项目）
        self.target_to_info: Dict[str, List[tuple]] = {}
        # 投资标的 -> 文件夹路径列表
        self.target_folders: Dict[str, List[Path]] = {}

        for _, row in df.iterrows():
            code = self._safe_str(row[code_col])
            target = self._safe_str(row[target_col])
            name = self._safe_str(row[name_col])
            account = self._safe_str(row[account_col])
            if not target or target == 'nan' or target == '' or not name or name == 'nan':
                continue

            # 科目代码末位（如 "1101.09.01.01.SQF409" -> "SQF409"）
            account_code = account.split('.')[-1] if account and account != 'nan' else ''

            self.target_to_info.setdefault(target, []).append((code, name))
            self.name_to_targets.setdefault(name, set()).add(target)

            if account_code and account_code not in ('nan', ''):
                self.code_to_targets.setdefault(account_code, []).append((target, name, code))

        # 建立投资标的 -> 文件夹路径列表
        # 文件夹结构: output_base / 项目代码_项目名称 / [投资标的/] 文件
        for name, targets in self.name_to_targets.items():
            # 找到属于该项目的项目代码
            proj_code = ''
            for tgt in targets:
                for c, n in self.target_to_info.get(tgt, []):
                    if n == name:
                        proj_code = c
                        break
                if proj_code:
                    break
            proj_folder_name = f"{proj_code}_{name}" if proj_code else name
            proj_folder = self.output_base / self._clean_filename(proj_folder_name)
            proj_folder.mkdir(parents=True, exist_ok=True)

            if len(targets) == 1:
                tgt = list(targets)[0]
                if tgt not in self.target_folders:
                    self.target_folders[tgt] = []
                self.target_folders[tgt].append(proj_folder)
            else:
                for tgt in targets:
                    tgt_folder = proj_folder / self._clean_filename(tgt)
                    tgt_folder.mkdir(parents=True, exist_ok=True)
                    if tgt not in self.target_folders:
                        self.target_folders[tgt] = []
                    self.target_folders[tgt].append(tgt_folder)

        logger.info(f"共 {len(self.code_to_targets)} 个科目代码, {len(self.target_to_info)} 个投资标的, {len(self.name_to_targets)} 个项目, {len(self.target_folders)} 个目标文件夹")
        return True

    def _extract_date_from_filename(self, filename: str) -> str:
        """从文件名提取日期"""
        patterns = [
            r'(\d{8})',           # 20260313
            r'(\d{4}-\d{2}-\d{2})',  # 2026-03-13
            r'(\d{4}/\d{2}/\d{2})',  # 2026/03/13
            r'(\d{4}\.\d{2}\.\d{2})',  # 2026.03.13
            r'(\d{4}_\d{2}_\d{2})',  # 2026_03_13
        ]
        for pattern in patterns:
            m = re.search(pattern, filename)
            if m:
                return m.group(1).replace('/', '-').replace('.', '-').replace('_', '-')
        return None

    def _check_date_in_range(self, date_str: str) -> tuple:
        if not date_str:
            return False, None
        try:
            file_date = datetime.strptime(date_str.replace('-', ''), "%Y%m%d").date()
        except:
            return False, None
        if self.start_date and file_date < self.start_date:
            return False, file_date
        if self.end_date and file_date > self.end_date:
            return False, file_date
        return True, file_date

    def _extract_code_from_filename(self, filename: str) -> str:
        """从文件名提取科目代码末位（如 SQF409）"""
        # 常见格式: SQF409_中原旭诺一号私募证券投资基金_...
        # 或: SLE071黑翼恒享CTA-T8号私募证券投资基金... (无下划线)
        m = re.match(r'^([A-Z]{2,}\d+[A-Z0-9]*)_?.*$', filename)
        if m:
            return m.group(1)
        # 格式: 华泰证券_估值表_SZP514_嘉策...
        parts = filename.split('_')
        for p in parts:
            if re.match(r'^[A-Z]{2,}\d+[A-Z0-9]*$', p):
                return p
        return ''

    def classify(self):
        """执行文件分类"""
        logger.info("[步骤] 开始分类文件...")
        if not self.source_dir.exists():
            logger.error(f"源目录不存在: {self.source_dir}")
            return

        mail_folders = [f for f in self.source_dir.iterdir() if f.is_dir()]
        self.stats['total_emails'] = len(mail_folders)
        logger.info(f"找到 {len(mail_folders)} 个邮件文件夹")

        unmatched_dir = self.output_base / "_未匹配"
        unmatched_dir.mkdir(parents=True, exist_ok=True)
        date_fail_log = self.output_base / "_无法提取日期文件.txt"

        # 预编译投资标的子串匹配：按长度降序排列，最长的先匹配（更精确）
        sorted_targets = sorted(self.target_to_info.keys(), key=len, reverse=True)

        total_files = 0
        total_folders = len(mail_folders)
        for idx, folder in enumerate(mail_folders):
            if idx > 0 and idx % 5000 == 0:
                logger.info(f"分类进度: {idx}/{total_folders} ({idx*100//total_folders}%) | 已处理文件: {total_files} | 已复制: {self.stats['copied_files']}")
            # 直接扫描当前文件夹，不用 rglob 递归扫描（文件直接在邮件文件夹内）
            excel_files = [f for f in folder.iterdir()
                         if f.is_file() and f.suffix.lower() in ('.xlsx', '.xls')]
            if not excel_files:
                continue

            for file_path in excel_files:
                total_files += 1
                filename = file_path.name

                # 关键词过滤
                if self.filename_keyword and self.filename_keyword not in filename:
                    self.stats['skipped_by_keyword'] += 1
                    continue

                # 日期提取和范围过滤
                date_str = self._extract_date_from_filename(filename)
                if not date_str:
                    self.stats['skipped_by_date'] += 1
                    with open(date_fail_log, 'a', encoding='utf-8') as f:
                        f.write(f"{filename}\n")
                    continue

                in_range, file_date = self._check_date_in_range(date_str)
                if not in_range:
                    self.stats['skipped_by_date'] += 1
                    continue

                # 匹配策略1: 通过科目代码末位精确匹配
                code = self._extract_code_from_filename(filename)

                if code and code in self.code_to_targets:
                    entries = self.code_to_targets[code]
                    matched_target = entries[0][0]  # 投资标的
                    # 同一科目代码对应多个项目，复制到每个项目的文件夹
                    for tgt, proj_name, proj_code in entries:
                        for dest_folder in self.target_folders.get(tgt, []):
                            self._copy_file(file_path, dest_folder / filename, tgt, matched_target)
                    continue
                else:
                    # 匹配策略2: 通过投资标的子串匹配（sorted_targets 已按长度降序）
                    matched_target = None
                    for tgt in sorted_targets:
                        if tgt in filename:
                            matched_target = tgt
                            break

                if not matched_target:
                    dest = unmatched_dir / filename
                    try:
                        shutil.copy2(file_path, dest)
                    except:
                        pass
                    self.stats['unmatched_keyword'] += 1
                    continue

                # 复制文件到所有有该投资标的的项目的文件夹
                for dest_folder in self.target_folders.get(matched_target, []):
                    self._copy_file(file_path, dest_folder / filename, matched_target, matched_target)

        self.stats['total_files'] = total_files
        self._log_stats()

    def _copy_file(self, src: Path, dest: Path, target: str, keyword: str):
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                return
            shutil.copy2(src, dest)
            self.copied_records.append({
                '投资标的': target,
                '关键词': keyword,
                '文件路径': str(dest)
            })
            self.newly_copied_files.append(dest)
            self.stats['copied_files'] += 1
        except Exception as e:
            logger.error(f"复制失败: {e}")

    def mark_status(self) -> Path:
        """标记Excel状态 - 根据文件夹中是否存在文件标记"是否找到"列"""
        logger.info("[步骤] 更新Excel状态标记...")
        if not self.project_file.exists():
            logger.error(f"原始文件不存在")
            return None

        df = pd.read_excel(self.project_file, header=0)
        cols = list(df.columns)
        target_col = cols[5]  # 投资标的

        status_col = "是否找到"
        if status_col not in df.columns:
            df[status_col] = "否"
        else:
            df[status_col] = "否"

        found = 0
        for idx, row in df.iterrows():
            target = self._safe_str(row[target_col])
            if not target or target == 'nan' or target == '':
                continue

            folders = self.target_folders.get(target, [])
            for dest_folder in folders:
                if dest_folder.exists():
                    if list(dest_folder.glob('*.xlsx')) or list(dest_folder.glob('*.xls')):
                        df.at[idx, status_col] = "是"
                        found += 1
                        break

        out_path = self.project_file.parent / (self.project_file.stem + "_已标记.xlsx")
        df.to_excel(out_path, index=False)
        logger.info(f"标记完成，{found} 行为'是'，结果保存至: {out_path}")
        return out_path

    def generate_report(self):
        """生成分类报告"""
        logger.info("[步骤] 生成报告...")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        if self.copied_records:
            df = pd.DataFrame(self.copied_records)
            df.to_excel(self.output_base / f'复制记录_{timestamp}.xlsx', index=False)
            logger.info("复制记录已保存")

        folder_stats = []
        for target, folders in self.target_folders.items():
            info_list = self.target_to_info.get(target, [('', '')])
            code, name = info_list[0]
            for folder in folders:
                files = list(folder.rglob('*.xlsx')) + list(folder.rglob('*.xls'))
                if files:
                    folder_stats.append({
                        '投资标的': target,
                        '项目代码': code,
                        'Excel文件总数': len(files)
                    })

        if folder_stats:
            df = pd.DataFrame(folder_stats)
            df.to_excel(self.output_base / f'分类报告_{timestamp}.xlsx', index=False)
            logger.info("分类报告已保存")

        logger.info(f"\n{'='*50}\n📊 分类统计\n{'='*50}")
        for k, v in self.stats.items():
            logger.info(f"{k}: {v}")

    def _log_stats(self):
        logger.info(f"\n✅ 分类完成:")
        logger.info(f"  邮件文件夹数: {self.stats['total_emails']}")
        logger.info(f"  处理文件总数: {self.stats['total_files']}")
        logger.info(f"  因关键词跳过: {self.stats['skipped_by_keyword']}")
        logger.info(f"  因日期跳过: {self.stats['skipped_by_date']}")
        logger.info(f"  未匹配关键词: {self.stats['unmatched_keyword']}")
        logger.info(f"  关键词无投资标的: {self.stats['unmatched_target']}")
        logger.info(f"  成功复制文件数: {self.stats['copied_files']}")

    def run(self):
        """执行完整流程：分类 → 标记 → 报告"""
        if not self.load_project_info():
            return None
        self.classify()
        self.mark_status()
        self.generate_report()
        logger.success("分类完成！")
        return self.newly_copied_files
