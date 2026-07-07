"""
邮件采集器 - 整合 MailListFetcher 和 MailDownloader
用法:
    from collectors.email_collector import EmailCollector
    ec = EmailCollector(config)
    ec.connect()
    mail_list = ec.fetch_mail_list(since="20260501", before="20260512")
    ec.export_mail_list(mail_list, "邮件列表.xlsx")
    ec.download_attachments(mail_list, save_dir)
    ec.disconnect()
"""

import imaplib
from pathlib import Path
from typing import List
from loguru import logger

from core.models import ValuationFile
from .mail_list import MailListFetcher
from .mail_downloader import MailDownloader


class EmailCollector(MailListFetcher, MailDownloader):
    """邮件采集器（组合版）- 继承邮件列表获取和附件下载功能"""

    def __init__(self, config: dict):
        MailListFetcher.__init__(self, config)
        MailDownloader.__init__(self, config)
        # 修正线程数：两个父类都用 self.threads，会被覆盖
        # 需要分别保存，让 fetch_mail_list 和 download_attachments_by_uids 用正确的值
        self.list_threads = config.get("mail_list_threads", 10)
        self.download_threads_attr = config.get("download_threads", 20)

    def fetch_mail_list(self, since_date: str = None, before_date: str = None) -> List[dict]:
        self.threads = self.list_threads  # 使用邮件列表线程数
        return MailListFetcher.fetch(self, since_date, before_date)

    def export_mail_list(self, mail_list: List[dict], output_path: Path):
        MailListFetcher.export_to_excel(self, mail_list, output_path)

    def download_attachments_by_uids(self, uids: List[str], save_dir: Path,
                                     mail_list: List[dict] = None) -> List[ValuationFile]:
        self.threads = self.download_threads_attr  # 使用附件下载线程数
        return MailDownloader.download(self, uids, save_dir, mail_list)
