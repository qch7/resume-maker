"""Codex 适配器的注册和生命周期入口"""

from resume_maker.plugins.support import dependency, publish, routes


def run_model(*args, **kwargs):
    """生产传输入口可单独注入，协议测试仍能直接验证真实 CLI 适配器"""
    from resume_maker.plugin_packages.ext_provider_codex.integrations.providers.cli import run_cli

    return run_cli(*args, **kwargs)


def activate(context):
    """Codex 提供传输及本机检查，业务依赖统一隐私出口"""
    from resume_maker.plugin_packages.ext_provider_codex.integrations.providers.cli import (
        inspect_cli,
    )

    sandbox = dependency(context, "sandbox")
    execution = dependency(context, "execution")
    credentials = dependency(context, "credentials")

    def transport(*args, **kwargs):
        """所有生产模型调用使用系统授权、会话和凭据借用"""
        return run_model(
            *args,
            **kwargs,
            sandbox=sandbox,
            execution=execution,
            credentials=credentials,
            generation=context.generation,
        )

    publish(context, "model.transport", transport, observed=False)
    publish(context, "model.inspection", inspect_cli, observed=False)
    routes(context, "resume_maker.plugin_packages.ext_provider_codex.routes.settings")
