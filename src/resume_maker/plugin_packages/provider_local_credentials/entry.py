"""本地凭据后端的注册和生命周期入口"""

from resume_maker.plugins.support import dependency, publish


def activate(context):
    """本机无登录也可创建凭据服务，引用只在请求时登记"""
    from resume_maker.infrastructure.credential_vault import CredentialVault

    directory = dependency(context, "config").data_dir / "credential-vault"
    vault = publish(context, "credentials.backend", CredentialVault(directory), observed=False)
    context.effect(vault.close)
