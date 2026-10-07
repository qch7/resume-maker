"""Word 插件通过系统执行和 sandbox 取得每轮受管进程"""

import threading

from resume_maker.core.errors import Problem
from resume_maker.core.process_environment import EnvironmentPolicy, process_environment
from resume_maker.plugin_packages.ext_word.integrations.word.rendering import (
    render_word,
    word_process,
)


class ControlledWord:
    """持有当前插件代次和取消句柄，关闭时等待真实进程结束"""

    def __init__(self, execution, sandbox, generation):
        """系统边界由装配注入，文档模块不自行挑选进程后端"""
        self.execution, self.sandbox, self.generation = execution, sandbox, generation
        self.condition = threading.Condition()
        self.active = set()
        self.stopped = False

    def execute(self, command, *, cwd, timeout):
        """为固定命令和工作目录签发一次授权，保留 Word 所需的本机环境"""
        flag = threading.Event()
        with self.condition:
            if self.stopped:
                raise Problem("Word 插件正在停止。", 409)
            self.active.add(flag)
        grant = None
        try:
            environment = process_environment(EnvironmentPolicy.DESKTOP)
            grant = self.sandbox.authorize(
                "ext.word",
                "document.local-render",
                self.generation,
                ["process_cleanup"],
                command=command,
                cwd=cwd,
                env=environment,
            )
            return self.execution.execute(
                grant,
                command,
                cwd=cwd,
                env=environment,
                timeout=timeout,
                cancelled=flag,
                stdin="",
            )
        finally:
            if grant is not None:
                self.execution.revoke(grant)
            with self.condition:
                self.active.discard(flag)
                self.condition.notify_all()

    def render(self, source, output):
        """DOCX 先由所选引擎生成，再用 Word 精确排版"""
        return render_word(source, output, executor=self.execute)

    def convert(self, source, output):
        """旧文档转换使用相同授权和进程回收边界"""
        return word_process(source, output, "convert", executor=self.execute)

    def close(self):
        """取消后等待实际退出，超时保留所有权并报告失败"""
        with self.condition:
            self.stopped = True
            for flag in self.active:
                flag.set()
            if not self.condition.wait_for(lambda: not self.active, timeout=30):
                raise Problem("Word 执行尚未结束，保留其依赖资源。", 409)
