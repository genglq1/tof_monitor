import imaplib
import ssl
import email
import re
import json
import time
import queue
import threading
import zipfile
import hashlib
import shutil
from pathlib import Path
from typing import List, Optional
from email.header import decode_header
from loguru import logger

from core.models import ValuationFile


class MailDownloader:
    """邮件附件下载器 - 多线程下载、哈希去重、断点续传"""

    def __init__(self, config: dict):
        self.config = config
        self.threads = config.get("download_threads", 20)
        self.batch_size = config.get("batch_size", 5)
        self.timeout = config.get("download_timeout", 120)
        self.max_retries = config.get("download_retry", 2)
        self.max_attachment_size = config.get("max_attachment_size", 100)  # MB
        self.use_hash = config.get("use_hash", True)
        self.extract_zip = config.get("extract_zip", True)
        self.hash_file = Path(config.get("hash_cache", "data/cache/mail_hash.json"))
        self.hash_set = self._load_hashes()
        self.hash_lock = threading.Lock()
        self.stats = {"files": 0, "no_attach": 0, "failed": 0, "skipped": 0}
        self.stat_lock = threading.Lock()
        self.done = 0
        self.done_lock = threading.Lock()
        self._decode_cache = {}
        self._clean_cache = {}

    def download(self, uids: List[str], save_dir: Path,
                 mail_list: List[dict] = None) -> List[ValuationFile]:
        """下载附件"""
        task_queue = queue.Queue()
        for uid in uids:
            task_queue.put(uid)

        results = []
        lock = threading.Lock()
        self.stats = {"files": 0, "no_attach": 0, "failed": 0, "skipped": 0}
        self.done = 0

        # 下载开始前，清理一次所有 IMAP 格式的旧文件夹（只清理一次）
        raw_dir = save_dir / "_原始邮件"
        if raw_dir.exists():
            for existing in raw_dir.iterdir():
                if existing.is_dir() and re.match(r'^\d+\s*\(UID\s+\d+\s+RFC822', existing.name):
                    try:
                        shutil.rmtree(existing)
                        logger.info(f"下载前清理旧IMAP文件夹: {existing.name}")
                    except Exception as e:
                        logger.warning(f"清理旧IMAP文件夹失败: {e}")

        # 构建序号和信息映射
        seq_map = {}
        uid_to_info = {}
        if mail_list:
            for idx, m in enumerate(mail_list, 1):
                seq_map[m['uid']] = idx
                uid_to_info[m['uid']] = m

        def worker():
            own_mail = self._login()
            if not own_mail:
                return
            while True:
                batch = self._get_batch(task_queue)
                if not batch:
                    break
                try:
                    self._process_batch(own_mail, batch, save_dir, results, lock,
                                     seq_map, uid_to_info)
                except (imaplib.IMAP4.error, OSError, EOFError) as e:
                    # 连接断开，重建连接后重试
                    logger.warning(f"连接断开，线程重连: {e}")
                    try:
                        own_mail.logout()
                    except:
                        pass
                    own_mail = self._login()
                    if not own_mail:
                        # 无法重连，把剩余任务标记失败
                        for _ in batch:
                            with self.stat_lock:
                                self.stats["failed"] += 1
                            with self.done_lock:
                                self.done += 1
                        continue
                    # 重连后重试当前批次
                    self._process_batch(own_mail, batch, save_dir, results, lock,
                                        seq_map, uid_to_info)
            try:
                own_mail.logout()
            except:
                pass

        threads_list = [threading.Thread(target=worker) for _ in range(self.threads)]
        for t in threads_list:
            t.start()

        self._wait_for_complete(len(uids))
        for t in threads_list:
            t.join()

        logger.success(f"下载完成: 附件{self.stats['files']} 无附件{self.stats['no_attach']} "
                      f"失败{self.stats['failed']} 跳过{self.stats['skipped']}")
        self._save_hashes()
        return results

    def _get_batch(self, q: queue.Queue) -> List[str]:
        batch = []
        while len(batch) < self.batch_size:
            try:
                batch.append(q.get_nowait())
            except queue.Empty:
                break
        return batch

    def _process_batch(self, mail, batch, save_dir, results, lock,
                       seq_map, uid_to_info):
        if self.batch_size > 1:
            # 先用 mail_info 快速检查已下载的，跳过不必要的 IMAP 请求
            raw_dir = save_dir / "_原始邮件"
            need_fetch = []
            for uid in batch:
                mail_info = uid_to_info.get(uid)
                if mail_info:
                    subject = mail_info.get('subject', '')
                    safe_subj = self._clean_filename(subject)[:50]
                    seq = seq_map.get(uid)
                    folder_name = f"{seq:06d}_{safe_subj}" if seq else f"{uid}_{safe_subj}"
                    folder = raw_dir / folder_name
                    if folder.exists():
                        with self.stat_lock:
                            self.stats["skipped"] += 1
                        with self.done_lock:
                            self.done += 1
                        continue
                need_fetch.append(uid)

            if not need_fetch:
                return

            uid_strs = ",".join(need_fetch)
            try:
                res, data = mail.uid('FETCH', uid_strs, '(RFC822)')
                if res == 'OK' and data:
                    msg_tuples = [item for item in data if isinstance(item, tuple) and len(item) >= 2]
                    for item in msg_tuples:
                        try:
                            msg = email.message_from_bytes(item[1])
                            # 从 IMAP 响应行提取真正的 UID
                            # 响应格式: "* N (UID <uid> RFC822 {size}_"
                            response = item[0].decode() if isinstance(item[0], bytes) else item[0]
                            uid_match = re.search(r'UID\s+(\d+)', response)
                            fetched_uid = uid_match.group(1) if uid_match else response
                            self._process_one(fetched_uid, msg, save_dir, results, lock,
                                              seq_map.get(fetched_uid), uid_to_info.get(fetched_uid))
                        except Exception:
                            with self.stat_lock:
                                self.stats["failed"] += 1
                        finally:
                            with self.done_lock:
                                self.done += 1
                    # 降级单封：服务器没返回的
                    def extract_uid(response_bytes):
                        response = response_bytes.decode() if isinstance(response_bytes, bytes) else response_bytes
                        m = re.search(r'UID\s+(\d+)', response)
                        return m.group(1) if m else response
                    fetched_uids = {extract_uid(item[0]) for item in msg_tuples}
                    for uid in need_fetch:
                        uid_str = uid.encode() if isinstance(uid, str) else uid
                        uid_decoded = uid_str.decode() if isinstance(uid_str, bytes) else uid
                        if uid_decoded not in fetched_uids:
                            self._fetch_and_process(mail, uid, save_dir, results, lock,
                                                   seq_map.get(uid), uid_to_info.get(uid))
                else:
                    for uid in need_fetch:
                        self._fetch_and_process(mail, uid, save_dir, results, lock,
                                               seq_map.get(uid), uid_to_info.get(uid))
            except Exception as e:
                logger.warning(f"批量FETCH失败，降级单封: {e}")
                for uid in need_fetch:
                    self._fetch_and_process(mail, uid, save_dir, results, lock,
                                           seq_map.get(uid), uid_to_info.get(uid))
        else:
            for uid in batch:
                self._fetch_and_process(mail, uid, save_dir, results, lock,
                                       seq_map.get(uid), uid_to_info.get(uid))

    def _fetch_and_process(self, mail, uid, save_dir, results, lock, seq=None, mail_info=None):
        try:
            # 快速路径：文件夹已存在则跳过，无需下载邮件
            if mail_info:
                subject = mail_info.get('subject', '')
                safe_subj = self._clean_filename(subject)[:50]
                folder_name = f"{seq:06d}_{safe_subj}" if seq else f"{uid}_{safe_subj}"
                folder = save_dir / "_原始邮件" / folder_name
                if folder.exists():
                    with self.stat_lock:
                        self.stats["skipped"] += 1
                    return

            retry_count = 0
            last_error = None
            while retry_count <= self.max_retries:
                try:
                    res, data = mail.uid('FETCH', uid.encode(), '(RFC822)')
                    if res == 'OK' and data and data[0] and len(data[0]) >= 2:
                        msg = email.message_from_bytes(data[0][1])
                        self._process_one(uid, msg, save_dir, results, lock, seq, mail_info)
                        return
                    else:
                        with self.stat_lock:
                            self.stats["failed"] += 1
                        return
                except (imaplib.IMAP4.error, OSError, EOFError, ssl.SSLError) as e:
                    last_error = e
                    retry_count += 1
                    if retry_count > self.max_retries:
                        break
                    logger.warning(f"连接断开，尝试重新登录 (第{retry_count}次) UID={uid}: {e}")
                    try:
                        mail.logout()
                    except:
                        pass
                    new_mail = self._login()
                    if new_mail:
                        mail = new_mail
                    else:
                        break
                except Exception as e:
                    last_error = e
                    break

            with self.stat_lock:
                self.stats["failed"] += 1
            if last_error:
                logger.error(f"下载失败 UID={uid} (已重试{self.max_retries}次): {last_error}")
        finally:
            with self.done_lock:
                self.done += 1

    def _process_one(self, uid, msg, save_dir, results, lock,
                     seq=None, mail_info=None):
        """处理单封邮件，返回: 1=成功, 0=无附件, -1=跳过(文件夹已存在)"""
        subject = self._decode_str(msg.get('Subject', ''))

        # 再次清理，确保移除任何 IMAP 协议前缀
        clean_subject = self._clean_filename(subject)
        safe_subj = clean_subject[:50]
        folder_name = f"{seq:06d}_{safe_subj}" if seq else f"{uid}_{safe_subj}"

        raw_dir = save_dir / "_原始邮件"
        raw_dir.mkdir(parents=True, exist_ok=True)
        folder = raw_dir / folder_name

        if folder.exists():
            with self.stat_lock:
                self.stats["skipped"] += 1
            return -1  # 跳过：已处理

        try:
            folder.mkdir(parents=True)
        except FileExistsError:
            with self.stat_lock:
                self.stats["skipped"] += 1
            return -1
        except:
            return -1

        file_cnt = 0
        hash_skipped = 0
        for part in msg.walk():
            if part.get_content_maintype() == 'multipart':
                continue
            raw_fn = part.get_filename()
            filename = self._decode_filename(raw_fn) if raw_fn else None
            if not filename:
                continue
            try:
                data = part.get_payload(decode=True)
                if not data:
                    continue
            except:
                continue

            # 检查附件大小
            if self.max_attachment_size > 0:
                size_mb = len(data) / (1024 * 1024)
                if size_mb > self.max_attachment_size:
                    logger.warning(f"附件过大，跳过: {filename} ({size_mb:.1f}MB > {self.max_attachment_size}MB)")
                    continue

            if self.use_hash:
                h = self._md5(data)
                with self.hash_lock:
                    if h in self.hash_set:
                        hash_skipped += 1
                        continue
                    self.hash_set.add(h)

            safe_name = self._clean_filename(self._decode_str(filename)).lstrip('\\/')
            file_path = folder / safe_name
            try:
                with open(file_path, 'wb') as f:
                    f.write(data)
                file_cnt += 1
            except Exception as e:
                logger.error(f"写入失败: {file_path} - {e}")
                continue

            if self.extract_zip and file_path.suffix.lower() == '.zip':
                self._extract_zip(file_path)

        # 保存邮件元数据
        if mail_info or file_cnt > 0:
            info = {
                '序号': seq,
                'UID': uid,
                '标题': subject,
                '发件人': mail_info.get('from', '') if mail_info else '',
                '日期': mail_info.get('date', '') if mail_info else '',
                '附件数': file_cnt
            }
            try:
                with open(folder / "_邮件信息.json", 'w', encoding='utf-8') as f:
                    json.dump(info, f, ensure_ascii=False, indent=2)
            except:
                pass

        with self.stat_lock:
            if file_cnt > 0:
                self.stats["files"] += file_cnt
            elif hash_skipped > 0:
                self.stats["skipped"] += hash_skipped
            else:
                self.stats["no_attach"] += 1

        code = self._extract_code(subject)
        level = "trust" if "信托" in subject else "underlying"
        with lock:
            results.append(ValuationFile(
                file_path=str(folder),
                project_code=code,
                project_name=subject,
                level=level
            ))
        return 1

    def _extract_zip(self, zip_path: Path):
        """解压 ZIP（支持 GBK 编码）"""
        target = zip_path.parent
        try:
            with zipfile.ZipFile(zip_path, 'r') as zf:
                zf.extractall(target)
            logger.info(f"已解压: {zip_path}")
        except UnicodeDecodeError:
            try:
                with zipfile.ZipFile(zip_path, 'r') as zf:
                    for info in zf.infolist():
                        try:
                            fn = info.filename.encode('cp437').decode('gbk')
                        except:
                            fn = info.filename
                        path = target / fn
                        if info.is_dir():
                            path.mkdir(parents=True, exist_ok=True)
                        else:
                            path.write_bytes(zf.read(info))
                logger.info(f"已解压(GBK): {zip_path}")
            except Exception as e:
                logger.error(f"解压失败 {zip_path}: {e}")
        except Exception as e:
            logger.error(f"解压失败 {zip_path}: {e}")

    def _load_hashes(self) -> set:
        if not self.use_hash:
            return set()
        try:
            if self.hash_file.exists():
                with open(self.hash_file, 'r', encoding='utf-8') as f:
                    return set(json.load(f))
        except:
            pass
        return set()

    def _save_hashes(self):
        if not self.use_hash:
            return
        self.hash_file.parent.mkdir(parents=True, exist_ok=True)
        with self.hash_lock:
            with open(self.hash_file, 'w', encoding='utf-8') as f:
                json.dump(list(self.hash_set), f)

    def _login(self):
        try:
            ctx = ssl.SSLContext(ssl.PROTOCOL_SSLv23)
            ctx.minimum_version = ssl.TLSVersion.TLSv1_2
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            ctx.set_ciphers('AES128-SHA:AES256-SHA')
            m = imaplib.IMAP4_SSL(self.config["server"], self.config.get("port", 993), ssl_context=ctx)
            m.login(self.config["username"], self.config["password"])
            m.select(self.config.get("folder", "INBOX"))
            return m
        except Exception as e:
            logger.error(f"线程登录失败: {e}")
            return None

    def _wait_for_complete(self, total: int):
        start = time.time()
        last_done = 0
        while self.done < total:
            time.sleep(1)
            elapsed = time.time() - start
            speed = self.done / elapsed * 60 if elapsed > 0 else 0
            if self.done - last_done >= 50 or self.done == total:
                logger.info(f"下载进度: {self.done}/{total} | 速度: {speed:.0f}封/分 | "
                           f"附件{self.stats['files']} 无附件{self.stats['no_attach']} "
                           f"跳过{self.stats['skipped']}")
                last_done = self.done

    def _decode_str(self, s: str) -> str:
        if not s:
            return ""
        if s in self._decode_cache:
            return self._decode_cache[s]
        try:
            decoded = decode_header(s)[0]
            res = decoded[0].decode(decoded[1], errors='ignore') if decoded[1] else str(decoded[0])
        except:
            res = str(s)
        self._decode_cache[s] = res
        return res

    def _decode_filename(self, encoded: str) -> str:
        """解码附件文件名（处理多行 GBK encoded-word）"""
        if not encoded:
            return ""
        try:
            parts = decode_header(encoded)
            result = []
            for part, charset in parts:
                if isinstance(part, bytes):
                    result.append(part.decode(charset or 'gbk', errors='ignore'))
                elif isinstance(part, str):
                    result.append(part)
            return ''.join(result)
        except:
            return str(encoded)

    def _clean_filename(self, name: str) -> str:
        if not name:
            return "未命名"
        name = str(name)
        # 移除 IMAP 协议响应格式前缀：匹配 "数字 (UID ... {数字}_" 格式并移除
        # 例如: "100000 (UID 1676029470 RFC822 {20980}_内容" -> "内容"
        m = re.match(r'^(\d+)\s*\(UID\s+\d+\s+RFC822\s+\{\d+\}_\s*(.*)', name, re.DOTALL)
        if m:
            name = m.group(2)
        name = re.sub(r'[\\/*?:"<>|]', '_', name)[:80]
        res = name.strip() or "未命名"
        return res

    def _extract_code(self, subject: str) -> str:
        m = re.search(r'ZY\d+[A-Z0-9]+', subject)
        return m.group(0) if m else "UNKNOWN"

    def _md5(self, data: bytes) -> str:
        return hashlib.md5(data).hexdigest()
