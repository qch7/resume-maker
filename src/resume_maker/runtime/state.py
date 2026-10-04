"""可恢复的配置提交记录，原子文件替换不冒充跨存储事务"""

import hashlib
import json
import os
from pathlib import Path

from resume_maker.runtime.graph import PluginError


def fingerprint(value: object) -> str:
    """对规范化 JSON 生成摘要，计划确认后内容变化必须重新计算"""
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


class StateStore:
    """配置快照和维护日志均不包含凭据或可执行代码"""

    def __init__(self, directory: Path):
        """启动只读取持久配置，不执行插件代码"""
        self.path = directory / "plugins.json"
        self.journal = directory / "plugins-operation.json"
        self.operations = directory / "plugin-operations"

    def save_plan(self, plan):
        """每个计划独立落盘，响应丢失后仍能查询真实阶段"""
        self.write(self.operations / (plan["id"] + ".json"), plan)

    def recover_plans(self):
        """以已提交配置判定中断计划，重启不自动重放变更或草稿确认"""
        result = {}
        saved = self.read()
        for path in sorted(self.operations.glob("*.json")):
            plan = json.loads(path.read_text(encoding="utf-8"))
            if path.stem != plan["id"]:
                raise PluginError("插件操作记录身份不匹配")
            if plan["state"] in {"planned", "preparing", "restart-required"}:
                committed = (
                    saved
                    and saved["generation"] == plan["generation"] + 1
                    and saved["selected"] == plan["selected"]
                    and saved.get("configs", {}) == plan["configs"]
                )
                plan["state"] = "committed" if committed else "interrupted"
                self.save_plan(plan)
            result[plan["id"]] = plan
        return result

    def read(self):
        """未知配置格式拒绝写入，未完成切换沿用上次已提交快照"""
        if not self.path.exists():
            return None
        value = json.loads(self.path.read_text(encoding="utf-8"))
        if value.get("version") != 1 or not isinstance(value.get("generation"), int):
            raise PluginError("插件配置格式不受当前运行时支持")
        if not isinstance(value.get("selected"), list) or not all(
            isinstance(item, str) for item in value["selected"]
        ):
            raise PluginError("插件选择数据无效")
        return value

    def write(self, path: Path, value):
        """先写临时文件并落盘，再在同目录原子替换"""
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".pending")
        with temporary.open("w", encoding="utf-8") as output:
            json.dump(value, output, ensure_ascii=False, indent=2)
            output.flush()
            os.fsync(output.fileno())
        temporary.replace(path)

    def begin(self, plan):
        """切换前留下恢复判据，启动从已提交配置重新装配"""
        self.write(self.journal, {"version": 1, "state": "preparing", "plan": plan})

    def commit(self, selected, generation, lock, configs=None, effective=None):
        """配置文件的替换是运行时代次的持久提交点"""
        self.write(
            self.path,
            {
                "version": 1,
                "generation": generation,
                "selected": sorted(selected),
                "lock": lock,
                "configs": configs or {},
                "effective": sorted(effective if effective is not None else selected),
            },
        )
        try:
            self.write(self.journal, {"version": 1, "state": "committed", "generation": generation})
        except OSError:
            # 配置替换已经提交，日志写入失败不能让运行态回退到另一代次
            pass

    def failed(self, message):
        """保留失败阶段供诊断，不删除此前已提交配置"""
        self.write(self.journal, {"version": 1, "state": "failed", "detail": message})
