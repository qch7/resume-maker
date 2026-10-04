"""平台提供方入口，系统职责不绑定具体实现"""

from resume_maker.plugins.support import dependency, publish, routes


def sqlite(context):
    """为工作区建立 SQLite 事务后端"""
    from resume_maker.infrastructure.database import Database

    config = context.host.bootstrap["config"]
    publish(
        context,
        "storage.backend",
        Database(
            config.data_dir / "resume.db",
            plugins={context.host.definition_id(key) for key in context.host.selected},
        ),
        observed=False,
    )


def local_assets(context):
    """提供显式的数据资源根目录"""
    publish(context, "assets.backend", context.host.bootstrap["config"].data_dir, observed=False)


def native_execution(context):
    """使用 Windows Job Object 或 POSIX 进程组的本机执行提供方"""
    from resume_maker.integrations.providers.process import execute

    publish(context, "execution.backend", execute, observed=False)


class LocalSandbox:
    """本机材料会话的真实强制能力报告"""

    capabilities = {
        "directory_acl": True,
        "tool_allowlist": True,
        "process_cleanup": True,
        "os_filesystem_isolation": False,
        "os_network_isolation": False,
    }

    def session(self):
        """使用独立控制目录和材料目录创建本轮会话"""
        from resume_maker.integrations.providers.sandbox import workspace

        return workspace()


def local_sandbox(context):
    """注册应用材料约束提供方，保持 OS 隔离能力明确为不可用"""
    publish(context, "sandbox.backend", LocalSandbox(), observed=False)


def local_credentials(context):
    """本机无登录也可创建凭据服务，引用只在请求时登记"""
    from resume_maker.infrastructure.credential_vault import CredentialVault

    vault = publish(context, "credentials.backend", CredentialVault(), observed=False)
    context.effect(vault.close)


def run_model(*args, **kwargs):
    """生产传输入口可单独注入，协议测试仍能直接验证真实 CLI 适配器"""
    from resume_maker.integrations.providers.cli import run_cli

    return run_cli(*args, **kwargs)


def codex(context):
    """Codex 提供传输及本机检查，业务依赖统一隐私出口"""
    from resume_maker.integrations.providers.cli import inspect_cli

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
    routes(context, "settings", only={"inspect_provider"})


def rapidocr(context):
    """登记本地 OCR 引擎，实际模型按现有线程锁延迟加载"""
    from resume_maker.integrations.local_ocr import read_document

    publish(context, "ocr.backend", read_document, observed=False)


def ocr(context):
    """发布当前选择的 OCR 提供方"""
    publish(context, "ocr", dependency(context, "ocr.backend"), observed=False)


def import_image(context):
    """注册图片解码入口，PDF 库不参与图片导入"""
    from resume_maker.integrations.certificates import prepare_certificate
    from resume_maker.integrations.document_importers import importer

    publish(context, "import.image", prepare_certificate, observed=False)
    context.contribute("documents.importers", "ext.import-image/default", importer("image"))


def import_pdf(context):
    """注册 PDF 解码入口，OCR 识别由独立插件负责"""
    from resume_maker.integrations.certificates import prepare_certificate
    from resume_maker.integrations.document_importers import importer

    publish(context, "import.pdf", prepare_certificate, observed=False)
    context.contribute("documents.importers", "ext.import-pdf/default", importer("pdf"))
    context.contribute(
        "documents.importers", "ext.import-pdf/scanned-docx", importer("scanned-docx")
    )
