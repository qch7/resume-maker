"""第三方凭据只保存引用，原值不进入配置、日志、响应或资料备份"""

import json
from contextlib import closing
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient

from resume_maker.api import create_app
from resume_maker.core.config import Config
from resume_maker.core.errors import Problem
from resume_maker.infrastructure.credential_vault import CredentialVault
from resume_maker.infrastructure.storage import create_backup, restore_backup
from resume_maker.runtime.graph import PluginError
from resume_maker.runtime.packages import PackageStore
from resume_maker.sdk.context import ServiceKey
from tests.support.plugins import bundle

HEADERS = {"x-resume-token": "test"}


def test_persistent_credential_is_bound_to_instance_and_purpose(tmp_path):
    """重启可继续借用，跨实例和用途失败，撤销只影响后续借用"""
    vault = CredentialVault(tmp_path / "vault")
    reference = vault.save("community.first", "ocr.auth", "synthetic-secret")
    vault.close()
    with pytest.raises(Problem, match="已停止"):
        with vault.borrow(reference, "community.first", "ocr.auth"):
            pass
    restarted = CredentialVault(tmp_path / "vault")
    with restarted.borrow(reference, "community.first", "ocr.auth") as value:
        assert value == "synthetic-secret"
    for owner, purpose in [("community.other", "ocr.auth"), ("community.first", "different")]:
        with pytest.raises(Problem):
            with restarted.borrow(reference, owner, purpose):
                pass
    with restarted.borrow(reference, "community.first", "ocr.auth") as value:
        restarted.revoke(reference)
        assert value == "synthetic-secret"
    with pytest.raises(Problem):
        with restarted.borrow(reference, "community.first", "ocr.auth"):
            pass


def test_credential_editor_api_keeps_secrets_out_of_configuration_and_backup(tmp_path):
    """真实外部包通过专用入口取得引用，配置计划拒绝密码原文"""
    archive = tmp_path / "credential.rmp"
    bundle(
        archive,
        extra={
            "host_api": ">=1.1.0 <2.0.0",
            "requires": {"host": {"credentials": ">=1.0.0 <2.0.0"}},
            "credential_fields": {"api_key": {"title": "API Key", "purpose": "ocr.auth"}},
            "config": {"api_key": ""},
            "config_schema": {
                "type": "object",
                "properties": {"api_key": {"type": "string", "format": "credential-ref"}},
                "additionalProperties": False,
            },
        },
    )
    directory = tmp_path / "data"
    app = create_app(Config(data_dir=directory, token="test", profile="minimal"))
    host = app.state.runtime
    manager = host.require(ServiceKey("plugins"))
    inspected = PackageStore(directory, set()).inspect(archive)
    manager.install(archive, inspected["digest"], inspected["trust_modes"])
    secret = "synthetic-credential-value"
    with TestClient(app) as client:
        # 采集 API 日志也不能记录合法或非法的凭据正文
        host.require(ServiceKey("db")).activity.capture_categories = frozenset({"api"})
        path = "/api/plugins/community.example/credentials/api_key"
        saved = client.put(
            path, headers=HEADERS, json={"generation": host.generation, "secret": secret}
        )
        assert saved.status_code == 200, saved.text
        reference = saved.json()["reference"]
        assert reference.startswith("cred.") and secret not in saved.text
        assert client.put(
            path, headers=HEADERS, json={"generation": host.generation - 1, "secret": secret}
        ).status_code in {409, 422}
        assert (
            client.put(
                path + "-unknown",
                headers=HEADERS,
                json={"generation": host.generation, "secret": secret},
            ).status_code
            == 404
        )
        invalid = client.put(
            path, headers=HEADERS, json={"generation": host.generation, "secret": secret * 1000}
        )
        assert invalid.status_code == 422 and secret not in invalid.text
        with pytest.raises(PluginError, match="只能保存"):
            manager.plan(
                host.selected, host.generation, configs={"community.example": {"api_key": secret}}
            )
        plan = manager.plan(
            host.selected, host.generation, configs={"community.example": {"api_key": reference}}
        )
        assert secret not in json.dumps(plan)
        assert secret not in client.get("/api/plugins", headers=HEADERS).text
        vault = host.require(ServiceKey("credentials"))
        with vault.borrow(reference, "community.example", "ocr.auth") as value:
            assert value == secret
        backup = create_backup(host.require(ServiceKey("db")), directory)
        with ZipFile(backup) as files:
            assert not any(name.startswith("credential-vault/") for name in files.namelist())
        logs = host.require(ServiceKey("db")).activity
        with closing(logs.connect()) as conn:
            assert secret not in json.dumps(
                [tuple(row) for row in conn.execute("SELECT * FROM activity")]
            )
    previous = restore_backup(backup, directory)
    assert previous is not None
    restored = CredentialVault(directory / "credential-vault")
    with restored.borrow(reference, "community.example", "ocr.auth") as value:
        assert value == secret
