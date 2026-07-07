import imaplib
import ssl
import socket
import email
import re
import time
import queue
import threading
import openpyxl
from pathlib import Path
from datetime import datetime
from typing import List
from email.header import decode_header
from email.utils import parsedate_to_datetime
from loguru import logger


class MailListFetcher:
    """邮件列表获取器 - 多线程并发获取邮件头信息"""

    def __init__(self, config: dict):
        self.config = config
        self.mail = None
        self.threads = config.get("mail_list_threads", 10)
        self.timeout = config.get("mail_list_timeout", 30)
        self.max_retries = config.get("mail_list_retry", 3)

    def connect(self):
        ctx = ssl.SSLContext(ssl.PROTOCOL_SSLv23)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        ctx.set_ciphers('AES128-SHA:AES256-SHA')
        self.mail = imaplib.IMAP4_SSL(
            self.config["server"],
            self.config.get("port", 993),
            ssl_context=ctx
        )
        self.mail.login(self.config["username"], self.config["password"])
        self.mail.select(self.config.get("folder", "INBOX"))
        logger.info("邮件服务器连接成功")

    def disconnect(self):
        if self.mail:
            try:
                self.mail.logout()
            except:
                pass

    def fetch(self, since_date: str = None, before_date: str = None) -> List[dict]:
        """多线程并发获取邮件列表"""
        criteria = []
        since_str = self._to_imap_date(since_date)
        before_str = self._to_imap_date(before_date)

        if since_str:
            criteria.append(f'SINCE "{since_str}"')
        if before_str:
            criteria.append(f'BEFORE "{before_str}"')

        search_cmd = ' '.join(criteria) if criteria else 'ALL'
        logger.info(f"搜索命令: {search_cmd}")

        status, data = self.mail.uid('SEARCH', None, search_cmd)
        if status != 'OK':
            logger.warning("搜索失败，回退为 ALL")
            status, data = self.mail.uid('SEARCH', None, 'ALL')
        if status != 'OK':
            logger.error("无法获取邮件列表")
            return []

        uids = data[0].split()
        total = len(uids)
        logger.info(f"找到 {total} 封邮件，使用 {self.threads} 个线程抓取...")

        since_naive = self._parse_to_naive(since_date)
        before_naive = self._parse_to_naive(before_date)

        work_queue = queue.Queue()
        for uid in uids:
            work_queue.put(uid)

        results = []
        results_lock = threading.Lock()

        def worker():
            try:
                ctx = ssl.SSLContext(ssl.PROTOCOL_SSLv23)
                ctx.minimum_version = ssl.TLSVersion.TLSv1_2
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                ctx.set_ciphers('AES128-SHA:AES256-SHA')
                mail = imaplib.IMAP4_SSL(
                    self.config["server"],
                    self.config.get("port", 993),
                    ssl_context=ctx
                )
                mail.login(self.config["username"], self.config["password"])
                mail.select(self.config.get("folder", "INBOX"))
            except Exception as e:
                logger.error(f"线程登录失败: {e}")
                return

            while True:
                try:
                    uid = work_queue.get(timeout=2)
                except queue.Empty:
                    break

                retry_count = 0
                last_error = None
                while retry_count <= self.max_retries:
                    try:
                        res, msg_data = mail.uid(
                            'FETCH', uid,
                            '(BODY.PEEK[HEADER.FIELDS (Subject From Date)])'
                        )
                        if res == 'OK' and msg_data and msg_data[0] and len(msg_data[0]) >= 2:
                            msg = email.message_from_bytes(msg_data[0][1])
                            subject = self._decode_str(msg.get('Subject', ''))
                            from_ = self._decode_str(msg.get('From', ''))
                            date_raw = msg.get('Date', '')
                            dt = None
                            try:
                                dt = parsedate_to_datetime(date_raw)
                                if dt and dt.tzinfo:
                                    dt = dt.replace(tzinfo=None)
                            except:
                                pass

                            # 日期过滤
                            if dt and since_naive and dt < since_naive:
                                break
                            if dt and before_naive and dt >= before_naive:
                                break

                            with results_lock:
                                results.append({
                                    'uid': uid.decode(),
                                    'subject': subject,
                                    'from': from_,
                                    'date': dt.strftime("%Y-%m-%d %H:%M:%S") if dt else date_raw,
                                })
                        break  # 成功或业务逻辑跳出
                    except (imaplib.IMAP4.error, OSError, socket.timeout, ssl.SSLError) as e:
                        last_error = e
                        retry_count += 1
                        if retry_count > self.max_retries:
                            break
                        logger.warning(f"邮件列表获取失败 UID={uid.decode()}, 重试({retry_count}/{self.max_retries}): {e}")
                        try:
                            mail.logout()
                        except:
                            pass
                        try:
                            ctx = ssl.SSLContext(ssl.PROTOCOL_SSLv23)
                            ctx.minimum_version = ssl.TLSVersion.TLSV1_2
                            ctx.check_hostname = False
                            ctx.verify_mode = ssl.CERT_NONE
                            ctx.set_ciphers('AES128-SHA:AES256-SHA')
                            mail = imaplib.IMAP4_SSL(
                                self.config["server"],
                                self.config.get("port", 993),
                                ssl_context=ctx
                            )
                            mail.login(self.config["username"], self.config["password"])
                            mail.select(self.config.get("folder", "INBOX"))
                        except:
                            break
                    except Exception as e:
                        last_error = e
                        break

                work_queue.task_done()

            try:
                mail.logout()
            except:
                pass

        # 启动线程
        threads = []
        for i in range(self.threads):
            t = threading.Thread(target=worker, name=f"mail-list-{i}")
            t.start()
            threads.append(t)

        # 进度监控
        start_time = time.time()
        last_count = 0
        while not work_queue.empty():
            time.sleep(2)
            processed = total - work_queue.qsize()
            elapsed = time.time() - start_time
            speed = processed / elapsed if elapsed > 0 else 0
            if processed - last_count >= 500 or work_queue.empty():
                eta = (total - processed) / speed if speed > 0 else 0
                logger.info(f"进度: {processed}/{total} ({processed/total*100:.1f}%) | "
                          f"速度: {speed:.1f} 封/秒 | 预计剩余: {eta:.0f}秒")
                last_count = processed

        for t in threads:
            t.join()

        # 按 UID 排序
        results.sort(key=lambda x: int(x['uid']))
        logger.info(f"获取完成，共 {len(results)} 封有效邮件")
        return results

    def export_to_excel(self, mail_list: List[dict], output_path: Path):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "邮件列表"
        ws.append(['序号', 'UID', '标题', '发件人', '收到时间'])
        for idx, m in enumerate(mail_list, 1):
            ws.append([f"{idx:06d}", m['uid'], m['subject'], m['from'], m['date']])
        ws.column_dimensions['A'].width = 10
        ws.column_dimensions['B'].width = 12
        ws.column_dimensions['C'].width = 60
        ws.column_dimensions['D'].width = 30
        ws.column_dimensions['E'].width = 20
        wb.save(output_path)
        logger.info(f"邮件列表已保存: {output_path}")

    def _to_imap_date(self, date_str: str):
        if not date_str:
            return None
        if re.match(r'^\d{8}$', date_str):
            try:
                dt = datetime.strptime(date_str, "%Y%m%d")
                return dt.strftime("%d-%b-%Y")
            except:
                return date_str
        return date_str

    def _parse_to_naive(self, d):
        if not d:
            return None
        try:
            if re.match(r'^\d{8}$', d):
                return datetime.strptime(d, "%Y%m%d")
            return datetime.strptime(d, "%d-%b-%Y")
        except:
            return None

    def _decode_str(self, s: str) -> str:
        if not s:
            return ""
        try:
            decoded = decode_header(s)[0]
            if decoded[1]:
                return decoded[0].decode(decoded[1], errors='ignore')
            return str(decoded[0])
        except:
            return str(s)
