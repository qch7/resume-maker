"""在只读快照中收集附加保护，失败时拒绝构造模型出口"""

import hashlib

from resume_maker.core.errors import Problem
from resume_maker.infrastructure.data_catalog import builtin_descriptors
from resume_maker.infrastructure.database import dump
from resume_maker.sdk.manifest import compatible
from resume_maker.sdk.privacy import PrivacyRuleContribution, PrivacyValues


def retained_private_data(db):
    """通过持久资料目录读取已存身份，停用或缺包不撤销这些保护"""
    builtins = builtin_descriptors()
    prefixes = set()
    for row in db.all("SELECT plugin_id,descriptor_json FROM plugin_data_catalog"):
        descriptor = row["descriptor"]
        prefixes.update(descriptor.get("privacy_settings", []))
        prefixes.update(builtins.get(row["plugin_id"], {}).get("privacy_settings", []))
    for prefix in sorted(prefixes):
        if not isinstance(prefix, str) or not prefix or len(prefix) > 250:
            raise Problem("持久隐私资料描述无效，已阻止外发。", 409)
        for row in db.all(
            "SELECT value_json FROM settings WHERE substr(key,1,?)=?", (len(prefix), prefix)
        ):
            yield row["value"]


class PrivacyContributions:
    """仅向系统引擎追加资料，规则代码不持有脱敏器及还原表"""

    def __init__(self, db, contributions):
        """持有独立工作区数据库和可撤销的规则集合"""
        self.db, self.contributions = db, contributions

    def entries(self):
        """校验规则身份、版本和说明，不执行规则代码"""
        entries = []
        for item in self.contributions("privacy.rule_contributions"):
            rule = item.value
            if (
                not isinstance(rule, PrivacyRuleContribution)
                or not item.identifier.startswith(item.owner + "/")
                or not compatible(rule.api_version, ">=1.0.0 <2.0.0")
                or not compatible(rule.version, ">=0.0.0")
                or not rule.title
                or len(rule.title) > 100
                or len(rule.description) > 1000
                or not callable(rule.collect)
            ):
                raise Problem(f"隐私规则贡献无效：{item.identifier}", 409)
            entries.append(item)
        return entries

    def describe(self):
        """公开规则用途和版本，敏感词及结构化资料不离开本机出口"""
        return [
            {
                "id": item.identifier,
                "title": item.value.title,
                "description": item.value.description,
                "version": item.value.version,
            }
            for item in self.entries()
        ]

    def snapshot(self):
        """固定同一读取快照，计算策略指纹以阻止迟到材料沿用旧规则"""
        values, identities = [], []
        with self.db.connect() as conn:
            conn.execute("BEGIN")
            for item in self.entries():
                reader = self.db.read_session(conn)
                try:
                    value = PrivacyValues.model_validate(item.value.collect(reader))
                    if any(not term.strip() or len(term) > 500 for term in value.terms):
                        raise ValueError("隐私词长度无效")
                    encoded = dump(value.model_dump()).encode()
                    if len(encoded) > 16 * 1024 * 1024:
                        raise ValueError("隐私贡献超出本机快照大小")
                except Exception as exc:
                    raise Problem(
                        f"隐私规则 {item.identifier} 读取失败，已阻止本次外发。", 409
                    ) from exc
                finally:
                    reader.close()
                values.append(value)
                identities.append(
                    (item.identifier, item.value.version, hashlib.sha256(encoded).hexdigest())
                )
        return values, hashlib.sha256(dump(identities).encode()).hexdigest() if identities else None
