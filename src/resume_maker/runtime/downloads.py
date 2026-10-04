"""显式来源和摘要的插件下载，进度和中断记录可跨请求查询"""

import hashlib
import json
import re
import threading
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import UUID

from resume_maker.core.errors import Problem
from resume_maker.runtime.state import StateStore, fingerprint

TERMINAL = {"ready", "failed", "cancelled", "interrupted"}
MAX_BYTES = 512 * 1024 * 1024


def validate_source(url):
    """下载只接受用户明确给出的 HTTPS 地址，不接受内嵌凭据或片段"""
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
        or len(url) > 4096
    ):
        raise Problem("请提供不含用户名、密码和片段的 HTTPS 插件下载地址。")


class Redirects(HTTPRedirectHandler):
    """重定向仍须满足来源协议，最终地址会写入下载记录"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        """拒绝 HTTPS 下载在中途降级到其他协议"""
        validate_source(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def open_source(url):
    """使用系统 TLS 信任和有界网络等待，不携带应用凭据"""
    return build_opener(Redirects()).open(
        Request(
            url, headers={"User-Agent": "ResumeMaker-Plugins/1", "Accept-Encoding": "identity"}
        ),
        timeout=5,
    )


class Downloads:
    """取消信号和实际下载结束分开，只有摘要通过后才发布可检查文件"""

    def __init__(self, directory, *, opener=open_source):
        """重启仅标记未完成下载，不自动重发网络请求"""
        self.root = Path(directory) / "plugin-downloads"
        self.writer, self.opener = StateStore(directory), opener
        self.lock, self.active = threading.RLock(), {}
        self.closed = False
        for path in self.root.glob("*/operation.json"):
            value = json.loads(path.read_text(encoding="utf-8"))
            if value["state"] not in TERMINAL:
                self._save({**value, "state": "interrupted", "message": "服务已停止，请重新下载。"})

    def _folder(self, identifier):
        """操作身份固定为 UUID，记录查询不能成为任意路径读取入口"""
        try:
            if str(UUID(identifier)) != identifier:
                raise ValueError(identifier)
        except (ValueError, TypeError) as exc:
            raise Problem("下载标识无效。") from exc
        folder = self.root / identifier
        if any(node.is_symlink() or node.is_junction() for node in (folder, *folder.parents)):
            raise Problem("下载目录包含链接。", 409)
        return folder

    def _save(self, value):
        """持久进度使用同一下载锁串行发布"""
        self.writer.write(self._folder(value["id"]) / "operation.json", value)

    def get(self, identifier):
        """丢失开始或取消响应后仍可按客户端预先生成的标识查询"""
        with self.lock:
            path = self._folder(identifier) / "operation.json"
            if not path.is_file():
                raise Problem("下载记录不存在。", 404)
            return json.loads(path.read_text(encoding="utf-8"))

    def list(self):
        """列出本机全部下载记录，未完成记录不会被当作可安装包"""
        with self.lock:
            return [self.get(path.parent.name) for path in self.root.glob("*/operation.json")]

    def start(self, identifier, url, sha256):
        """开始下载前固定来源和摘要，相同请求身份可安全重试"""
        validate_source(url)
        if not re.fullmatch(r"[a-f0-9]{64}", sha256):
            raise Problem("请填写发布者提供的完整 SHA-256 文件摘要。")
        spec = {"url": url, "sha256": sha256}
        with self.lock:
            folder = self._folder(identifier)
            if (folder / "operation.json").exists():
                previous = self.get(identifier)
                if previous["request_digest"] != fingerprint(spec):
                    raise Problem("该下载标识已用于另一份来源，请新建下载。", 409)
                return previous
            if self.closed:
                raise Problem("下载服务正在关闭。", 409)
            value = {
                "id": identifier,
                **spec,
                "request_digest": fingerprint(spec),
                "state": "downloading",
                "received": 0,
                "total": None,
                "path": None,
            }
            self._save(value)
            cancel = threading.Event()
            worker = threading.Thread(target=self._run, args=(value, cancel), daemon=True)
            self.active[identifier] = (cancel, worker)
            worker.start()
            return dict(value)

    def _run(self, value, cancel):
        """实际读取字节决定进度，文件落盘和摘要核验完成后才报告就绪"""
        import os

        folder = self._folder(value["id"])
        pending = folder / "package.partial"
        try:
            with self.opener(value["url"]) as response, pending.open("xb") as output:
                final_url = response.geturl()
                validate_source(final_url)
                total = response.headers.get("Content-Length")
                total = int(total) if total is not None else None
                if total is not None and not 0 <= total <= MAX_BYTES:
                    raise Problem("插件包超过 512 MB，请使用本地安装。")
                with self.lock:
                    value.update(total=total, final_url=final_url)
                    self._save(value)
                digest = hashlib.sha256()
                while not cancel.is_set():
                    chunk = response.read1(128 * 1024)
                    if not chunk:
                        break
                    if value["received"] + len(chunk) > MAX_BYTES:
                        raise Problem("插件包超过 512 MB，请使用本地安装。")
                    output.write(chunk)
                    digest.update(chunk)
                    with self.lock:
                        value["received"] += len(chunk)
                        if cancel.is_set():
                            value["state"] = "cancelling"
                        self._save(value)
                output.flush()
                os.fsync(output.fileno())
            with self.lock:
                if cancel.is_set():
                    value["state"] = "cancelled"
                else:
                    if (
                        total is not None and value["received"] != total
                    ) or digest.hexdigest() != value["sha256"]:
                        raise Problem("下载不完整或文件摘要不匹配，未发布安装包。")
                    target = folder / "package.rmp"
                    pending.replace(target)
                    value.update(state="ready", path=str(target.resolve()))
                self._save(value)
        except Exception as exc:
            with self.lock:
                value.update(
                    state="cancelled" if cancel.is_set() else "failed",
                    message=str(exc) if isinstance(exc, Problem) else type(exc).__name__,
                )
                self._save(value)
        finally:
            pending.unlink(missing_ok=True)
            with self.lock:
                self.active.pop(value["id"], None)

    def cancel(self, identifier):
        """立即记录取消意图，等待底层网络读取结束后才转成已取消"""
        with self.lock:
            value = self.get(identifier)
            if value["state"] not in TERMINAL and (active := self.active.get(identifier)):
                active[0].set()
                value["state"] = "cancelling"
                self._save(value)
            return value

    def close(self):
        """关闭时取消全部下载并等待工作线程实际退出"""
        with self.lock:
            self.closed = True
            active = tuple(self.active.values())
            for cancelled, _ in active:
                cancelled.set()
        for _, worker in active:
            worker.join(10)
            if worker.is_alive():
                raise Problem("插件下载尚未结束，请稍后重试关闭。", 409)
