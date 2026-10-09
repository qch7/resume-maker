"""插件下载的可恢复进度、摘要核验及取消后实际结束"""

import hashlib
import threading
from io import BytesIO
from uuid import uuid4

import pytest

from resume_maker.core.errors import Problem
from resume_maker.runtime.downloads import Downloads


class Response(BytesIO):
    """模拟已建立的 HTTPS 连接，不访问真实网络"""

    def __init__(self, data, gate=None):
        """只保存合成数据，可明确控制下一次读取何时结束"""
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}
        self.gate = gate
        self.started = threading.Event()

    def geturl(self):
        """报告经过合法重定向后的固定地址"""
        return "https://example.test/package.rmp"

    def read1(self, size=-1):
        """阻塞替身仍保留真实关闭时机，取消不能提前报告线程结束"""
        self.started.set()
        if self.gate is not None:
            assert self.gate.wait(5)
        return super().read(size)


def finish(service, identifier):
    """等待本轮下载实际完成，返回磁盘上的状态"""
    with service.lock:
        active = service.active.get(identifier)
    if active:
        active[1].join(5)
        assert not active[1].is_alive()
    return service.get(identifier)


def test_download_response_loss_reuses_id_and_verified_package(tmp_path):
    """开始请求重发只下载一次，重启后仍能定位原文件并读取完整进度"""
    raw = b"synthetic-package"
    calls = []

    def opener(url):
        """记录是否发生了重复网络请求"""
        calls.append(url)
        return Response(raw)

    service = Downloads(tmp_path, opener=opener)
    identifier, url, digest = (
        str(uuid4()),
        "https://example.test/package.rmp",
        hashlib.sha256(raw).hexdigest(),
    )
    service.start(identifier, url, digest)
    service.start(identifier, url, digest)
    result = finish(service, identifier)
    assert result["state"] == "ready"
    assert result["received"] == result["total"] == len(raw)
    assert len(calls) == 1
    assert Downloads(tmp_path).get(identifier) == result
    with pytest.raises(Problem, match="另一份来源"):
        service.start(identifier, url + "?different", digest)


def test_download_cancellation_waits_for_real_read_and_never_publishes(tmp_path):
    """读取尚未返回时保持取消中，实际退出后才清理部分文件"""
    gate = threading.Event()
    response = Response(b"bytes", gate)
    service = Downloads(tmp_path, opener=lambda _: response)
    identifier = str(uuid4())
    try:
        service.start(identifier, response.geturl(), hashlib.sha256(b"bytes").hexdigest())
        assert response.started.wait(2)
        assert service.cancel(identifier)["state"] == "cancelling"
        assert service.get(identifier)["state"] == "cancelling"
    finally:
        gate.set()
    assert finish(service, identifier)["state"] == "cancelled"
    assert not list(tmp_path.rglob("package.*"))


def test_wrong_download_digest_is_not_an_installable_file(tmp_path):
    """网络成功仍须验证发布者摘要，失败下载和中断进度不会误报就绪"""
    service = Downloads(tmp_path, opener=lambda _: Response(b"unexpected"))
    identifier = str(uuid4())
    service.start(identifier, "https://example.test/package.rmp", "0" * 64)
    result = finish(service, identifier)
    assert result["state"] == "failed" and result["path"] is None
    assert not list(tmp_path.rglob("package.*"))
