"""插件运行状态和客户端能力协商"""

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends
from jsonschema import Draft202012Validator
from pydantic import Field

from resume_maker.api.dependencies import service
from resume_maker.core.errors import Problem
from resume_maker.infrastructure.execution import Sandbox
from resume_maker.infrastructure.task_supervisor import TaskSupervisor
from resume_maker.runtime.manager import PluginManager
from resume_maker.runtime.worker import validate_schema
from resume_maker.sdk.manifest import Contract

router = APIRouter(prefix="/api", tags=["plugins"])


class SelectionInput(Contract):
    """完整候选选择和用于并发校验的配置代次"""

    selected: list[str] = Field(max_length=500)
    generation: int = Field(ge=1)
    configs: dict[str, dict] | None = None


class PlanInput(Contract):
    """用户确认的是具体摘要对应的计划"""

    digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class WindowInput(Contract):
    """窗口身份独立于实体和工作区恢复代次"""

    id: str = Field(min_length=1, max_length=100)
    generation: int = Field(ge=1)


class PackageInspectInput(Contract):
    """本机用户选择的完整插件包路径"""

    path: str = Field(min_length=1, max_length=4096)


class PackageInstallInput(PackageInspectInput):
    """安装同一份经过审查的产物并明确其代码信任模式"""

    digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    trusted_modes: list[str] = Field(max_length=4)


class RpcInput(Contract):
    """跨域操作固定调用窗口的代次，正文只能包含 JSON 值"""

    generation: int = Field(ge=1)
    payload: object


@router.post("/plugins/rpc/{plugin_id}/{method}")
def plugin_rpc(
    dep_plugins: Annotated[PluginManager, Depends(service("plugins"))],
    plugin_id: str,
    method: str,
    body: RpcInput,
):
    """以插件所有者取得请求租约，不向插件泄露实例令牌或服务容器"""
    manager = dep_plugins
    host = manager.host
    handler = host.rpc_handlers.get((plugin_id, method))
    if handler is None:
        raise Problem("远程操作不可用。", 404)
    contract = host.manifests[plugin_id].rpc[method]
    for schema in (contract.input_schema, contract.output_schema):
        validate_schema(schema)
    with manager.request(plugin_id, write=True, generation=body.generation):
        if not Draft202012Validator(contract.input_schema).is_valid(body.payload):
            raise Problem("远程操作输入不符合契约。", 422)
        result = handler(body.payload)
        if not Draft202012Validator(contract.output_schema).is_valid(result):
            raise Problem("插件返回值不符合远程契约。", 502)
        return result


@router.get("/plugins")
def installed_plugins(
    dep_plugins: Annotated[PluginManager, Depends(service("plugins"))],
    dep_tasks: Annotated[TaskSupervisor, Depends(service("tasks"))],
):
    """区分包安装、组合选择和实例运行状态"""
    host = dep_plugins.host
    return {
        "generation": host.generation,
        "plugins": host.status(),
        "desired": sorted(host.desired),
        "blocked": host.blocked,
        "profiles": dep_plugins.profiles,
        "task_persistence_errors": dep_tasks.diagnostics(),
    }


@router.get("/capabilities")
def capabilities(
    dep_plugins: Annotated[PluginManager, Depends(service("plugins"))],
    dep_sandbox: Annotated[Sandbox, Depends(service("sandbox"))],
):
    """客户端按同一代次协商可用能力和插件资源"""
    host = dep_plugins.host
    return {
        "generation": host.generation,
        "host_api": "1.0.0",
        "client_api": "1.0.0",
        "ready": not dep_plugins.maintenance
        and all(host.instances[key].state == "active" for key in host.required),
        "plugins": sorted(host.selected),
        "services": sorted(host.services),
        "sandbox": dep_sandbox.capabilities(),
        "client": [
            {
                "id": identifier,
                "entry": client_entry(host, identifier, manifest),
                "contributes": manifest.contributes,
                "provides": {
                    name: spec.model_dump()
                    for name, spec in manifest.provides.get("client", {}).items()
                },
                "bindings": {
                    domain: {
                        name: {
                            "owners": list(owners),
                            "many": not isinstance(manifest.requires[domain][name], str)
                            and manifest.requires[domain][name].cardinality == "many",
                        }
                        for (consumer, group, name), owners in host.resolution.bindings.items()
                        if consumer == identifier and group == domain
                    }
                    for domain in ("client", "remote")
                },
            }
            for identifier in host.resolution.client_order
            for manifest in [host.manifests[identifier]]
            if identifier in host.selected and "client" in manifest.entrypoints
        ],
    }


def client_entry(host, identifier, manifest):
    """外部客户端只使用已校验的内容摘要资源路径"""
    entry = manifest.entrypoints["client"].model_dump()
    if location := host.bootstrap["packages"].get(identifier):
        entry["entry"] = f"/plugin-assets/{identifier}/{location.name}/{entry['entry']}"
    return entry


@router.post("/plugins/packages/inspect")
def inspect_package(
    dep_plugins: Annotated[PluginManager, Depends(service("plugins"))], body: PackageInspectInput
):
    """读取包、摘要和依赖，检查期间不执行任何插件代码"""
    return dep_plugins.host.bootstrap["package_store"].inspect(Path(body.path))


@router.post("/plugins/packages/install")
def install_package(
    dep_plugins: Annotated[PluginManager, Depends(service("plugins"))], body: PackageInstallInput
):
    """安装和启用分开，权限及包内容变化时旧确认失效"""
    return dep_plugins.install(Path(body.path), body.digest, body.trusted_modes)


@router.delete("/plugins/packages/{plugin_id}")
def uninstall_package(
    dep_plugins: Annotated[PluginManager, Depends(service("plugins"))], plugin_id: str
):
    """只卸载已停止代码包，草稿、资料和资源仍随备份保留"""
    return dep_plugins.uninstall(plugin_id)


@router.post("/plugins/packages/{plugin_id}/environment")
def prepare_plugin_environment(
    dep_plugins: Annotated[PluginManager, Depends(service("plugins"))], plugin_id: str
):
    """用插件包中的完整离线 wheel 锁准备可重启选择的候选环境"""
    return dep_plugins.prepare_environment(plugin_id)


@router.post("/plugins/plans")
def plan_plugins(
    dep_plugins: Annotated[PluginManager, Depends(service("plugins"))], body: SelectionInput
):
    """生成依赖及中断范围明确的变更计划，尚不修改活动组合"""
    return dep_plugins.plan(body.selected, body.generation, body.configs)


@router.post("/plugins/plans/{plan_id}/prepare")
def prepare_plugins(
    dep_plugins: Annotated[PluginManager, Depends(service("plugins"))],
    plan_id: str,
    body: PlanInput,
):
    """通知已连接窗口刷新草稿，保留专用刷新通道"""
    return dep_plugins.prepare(plan_id, body.digest)


@router.get("/plugins/plans/{plan_id}")
def plugin_plan_progress(
    dep_plugins: Annotated[PluginManager, Depends(service("plugins"))], plan_id: str
):
    """查询未确认窗口和在途请求，不将等待超时当作用户确认"""
    return dep_plugins.progress(plan_id)


@router.post("/plugins/plans/{plan_id}/apply")
def apply_plugins(
    dep_plugins: Annotated[PluginManager, Depends(service("plugins"))],
    plan_id: str,
    body: PlanInput,
):
    """仅在窗口和请求排空后切换候选组合"""
    return dep_plugins.apply(plan_id, body.digest)


@router.post("/plugins/plans/{plan_id}/cancel-tasks")
def cancel_plugin_tasks(
    dep_plugins: Annotated[PluginManager, Depends(service("plugins"))],
    plan_id: str,
    body: PlanInput,
):
    """用户可取消影响范围内的任务，取消信号不等于排空完成"""
    return dep_plugins.cancel_tasks(plan_id, body.digest)


@router.post("/plugins/plans/{plan_id}/abort")
def abort_plugins(
    dep_plugins: Annotated[PluginManager, Depends(service("plugins"))],
    plan_id: str,
    body: PlanInput,
):
    """取消尚未提交的计划并保留所有已保存草稿"""
    dep_plugins.abort(plan_id, body.digest)
    return {"ok": True}


@router.post("/plugins/windows")
def plugin_window(
    dep_plugins: Annotated[PluginManager, Depends(service("plugins"))], body: WindowInput
):
    """登记窗口并读取需要确认的插件变更"""
    return dep_plugins.window(body.id, body.generation)


@router.post("/plugins/plans/{plan_id}/acknowledge")
def acknowledge_plugins(
    dep_plugins: Annotated[PluginManager, Depends(service("plugins"))],
    plan_id: str,
    body: WindowInput,
):
    """客户端完成领域及工作区草稿落盘后确认当前计划"""
    dep_plugins.acknowledge(body.id, plan_id, body.generation)
    return {"ok": True}


@router.post("/plugins/windows/close")
def close_plugin_window(
    dep_plugins: Annotated[PluginManager, Depends(service("plugins"))], body: WindowInput
):
    """仅正常持久化关闭才能撤销窗口注册"""
    dep_plugins.close_window(body.id, body.generation)
    return {"ok": True}


@router.post("/plugins/windows/disconnect")
def disconnect_plugin_window(
    dep_plugins: Annotated[PluginManager, Depends(service("plugins"))], body: WindowInput
):
    """页面离开不能充当草稿已保存的证明"""
    dep_plugins.disconnect(body.id, body.generation)
    return {"ok": True}


@router.post("/plugins/plans/{plan_id}/retain-window")
def retain_plugin_window(
    dep_plugins: Annotated[PluginManager, Depends(service("plugins"))],
    plan_id: str,
    body: WindowInput,
):
    """用户明确保留离线窗口的恢复副本，下一代次禁止自动覆盖正式输入"""
    dep_plugins.retain_window(body.id, plan_id, body.generation)
    return {"ok": True}
