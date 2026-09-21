"""有界读取 CLI 事件并回收本次调用的进程树"""

import json
import os
import queue
import signal
import subprocess
import threading
import time

import psutil

from resume_maker.integrations.providers.base import Cancelled, ProviderError

MAX_OUTPUT = 16 * 1024 * 1024
MAX_LINE = 4 * 1024 * 1024


def terminate(process):
    """只回收当前请求拥有的进程树，避免退出后仍有子进程占用管道"""
    try:
        parent = psutil.Process(process.pid)
        children = parent.children(recursive=True)
        for child in reversed(children):
            try:
                child.kill()
            except psutil.NoSuchProcess:
                pass
        parent.kill()
        psutil.wait_procs([parent, *children], timeout=2)
    except psutil.NoSuchProcess:
        pass


def windows_job(process):
    """将 CLI 和已有子进程纳入任务对象，关闭时统一终止未来后代"""
    if os.name != "nt":
        return None
    import win32api
    import win32job

    job = win32job.CreateJobObject(None, "")
    info = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)
    info["BasicLimitInformation"]["LimitFlags"] = win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    win32job.SetInformationJobObject(job, win32job.JobObjectExtendedLimitInformation, info)
    try:
        win32job.AssignProcessToJobObject(job, int(process._handle))
        for child in psutil.Process(process.pid).children(recursive=True):
            try:
                handle = win32api.OpenProcess(0x101 | 0x1000, False, child.pid)
                try:
                    win32job.AssignProcessToJobObject(job, handle)
                finally:
                    handle.Close()
            except (psutil.NoSuchProcess, OSError):
                pass
        return job
    except Exception:
        job.Close()
        terminate(process)
        raise


def execute(command, *, cwd, env, timeout, cancelled, stdin="", event=None):
    """通过有界队列接收输出，超时和取消及时关闭整个请求"""
    if cancelled.is_set():
        raise Cancelled("请求已取消。")
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=0x08000200 if os.name == "nt" else 0,
        start_new_session=os.name != "nt",
    )
    job = windows_job(process)
    lines, stopped = queue.Queue(maxsize=16), threading.Event()

    def enqueue(value):
        """停止后不再等待消费者，避免后台读取线程泄漏"""
        while not stopped.is_set():
            try:
                lines.put(value, timeout=0.1)
                return
            except queue.Full:
                pass

    def read(stream, channel):
        """限制单行尺寸，任何超限内容均不进入模型事件解析"""
        try:
            while raw := stream.readline(MAX_LINE + 1):
                enqueue((channel, raw))
                if len(raw) > MAX_LINE:
                    break
        finally:
            enqueue((channel, None))

    def write():
        """独立写入提示词，避免子进程不读取输入时阻塞取消"""
        try:
            process.stdin.write(stdin.encode("utf-8"))
            process.stdin.close()
        except (BrokenPipeError, OSError):
            pass

    workers = [
        threading.Thread(target=read, args=(process.stdout, "stdout"), daemon=True),
        threading.Thread(target=read, args=(process.stderr, "stderr"), daemon=True),
        threading.Thread(target=write, daemon=True),
    ]
    for worker in workers:
        worker.start()
    started, finished, total, output = time.monotonic(), set(), 0, []
    try:
        while len(finished) < 2:
            if cancelled.is_set():
                raise Cancelled("请求已取消。")
            if time.monotonic() - started > timeout:
                raise ProviderError("CLI 或沙箱检查超时，已停止本次请求。")
            try:
                channel, raw = lines.get(timeout=0.1)
            except queue.Empty:
                continue
            if raw is None:
                finished.add(channel)
                continue
            total += len(raw)
            if len(raw) > MAX_LINE or total > MAX_OUTPUT:
                raise ProviderError("CLI 输出超过大小限制，已停止本次请求。")
            if channel == "stdout":
                line = raw.decode("utf-8", "replace")
                if event:
                    try:
                        value = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(value, dict):
                        event(value)
                else:
                    output.append(line)
        if process.wait(timeout=2) != 0:
            raise ProviderError(
                "CLI 或隔离检查失败，未回退到未隔离模式。请检查 CLI 配置及沙箱环境。"
            )
        return "".join(output)
    finally:
        stopped.set()
        if job is not None:
            job.Close()
        elif os.name != "nt":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if process.poll() is None:
            terminate(process)
        for worker in workers:
            worker.join(timeout=1)
        for stream in (process.stdin, process.stdout, process.stderr):
            stream.close()
