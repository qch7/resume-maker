"""本机敏感值登记、请求脱敏和单次响应还原"""

import json
import re
import secrets
from urllib.parse import quote

from resume_maker.integrations.privacy_identifiers import (
    IDENTIFIER_KEYS,
    identifier_spans,
    identifier_values,
    literal_pattern,
)
from resume_maker.integrations.privacy_text import formatted_values, known_variants, labeled_values
from resume_maker.integrations.providers.base import ProviderError

TOKEN = re.compile(r"\[\[RM_[a-f0-9]{12}_\d+\]\]")
PATTERNS = [
    re.compile(r"(?i)[\w.+-]+@[\w.-]+\.[a-z]{2,}"),
    re.compile(r"(?<!\d)(?:\+?86[ -]?)?1[3-9]\d[ -]?\d{4}[ -]?\d{4}(?!\d)"),
    re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)"),
    re.compile(r"(?<!\d)\d{16,19}(?!\d)"),
    re.compile(r"(?<!\d)(?:\+\d{1,3}[ -])?0\d{2,3}[- ]\d{7,8}(?!\d)"),
    re.compile(r"(?i)https?://[^\s<>\"'，。；）)]+"),
    re.compile(r"(?i)(?:[a-z]:[\\/]|\\\\)[^\r\n\"<>|]+"),
    re.compile(r"/(?:home|Users|root)/[^\s\"'<>]+"),
    re.compile(r"(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)"),
]
LABEL = re.compile(
    r"(?im)(?:姓名|获奖人|持有人|联系人|身份证号?|证书编号|学号|住址|家庭地址|"
    r"出生日期|生日|毕业院校|就读学校|学校|院校|工作单位|颁发单位|颁发机构|发证机构|"
    r"联系电话|电话|手机|邮箱|name|recipient|address|issuer|issued[ \t]+by|school|"
    r"certificate[ _]?(?:number|no\.?))"
    r"[ \t]*(?:[:：=][ \t]*(?:\r?\n[ \t]*)?|\r?\n[ \t]*)"
    r"([^\r\n，,；;|<>]{1,120})"
)
NAMED_PERSON = re.compile(
    r"(?:我叫|本人(?:是)?|获奖人(?:为)?)[ \t]*([\u4e00-\u9fff]{2,4})(?=[，。\s]|$)|"
    r"([\u4e00-\u9fff]{2,4})(?=同学|先生|女士)"
)
SECRET_KEY = re.compile(
    r"(?i)^(?:api[_-]?key|access[_-]?token|secret|password|passwd|authorization|client_secret)$"
)
SECRET = re.compile(
    r"(?im)([\"']?(?:api[_-]?key|access[_-]?token|secret|password|passwd|"
    r"authorization|client_secret)[\"']?\s*[:=]\s*)([^\r\n,]+)"
)
BLOB = re.compile(r"(?i)data:[^\s,]+;base64,|[A-Za-z0-9+/]{512,}={0,2}")
KEYS = {
    "name",
    "recipient",
    "certificate_number",
    "phone",
    "mobile",
    "email",
    "address",
    "issuer",
    "passport",
    "id_number",
    "姓名",
    "身份证",
    "手机号",
    "证书编号",
}


class Redactor:
    """替换表仅在当前请求内存中存在，每次外发重新生成占位符"""

    def __init__(self, values=()):
        """初始化独立随机命名空间以防跨请求关联及占位符碰撞"""
        self.prefix = secrets.token_hex(6)
        self.mapping = {}
        self.secrets = set()
        self.values = set(
            value.strip() for value in values if isinstance(value, str) and value.strip()
        )
        self.count = 0

    def learn(self, value):
        """登记结构化个人资料及明确标注的身份字段，包括隐藏字段"""
        if isinstance(value, dict):
            if value.get("kind") == "education":
                for entry in value.get("entries", []):
                    self.values.update(
                        entry[key] for key in ("title", "subtitle") if entry.get(key)
                    )
            if isinstance(value.get("label"), str) and LABEL.search(value["label"] + ":标记"):
                if isinstance(value.get("value"), str) and value["value"].strip():
                    self.values.add(value["value"].strip())
            for key, child in value.items():
                if SECRET_KEY.fullmatch(key) and isinstance(child, str):
                    self.secrets.add(child)
                if key == "personal" and isinstance(child, dict):
                    self.values.update(
                        v.strip()
                        for k, v in child.items()
                        if isinstance(v, str) and v.strip() and k != "photo"
                    )
                    for field in child.get("custom_fields", []):
                        if field.get("value", "").strip():
                            self.values.add(field["value"].strip())
                elif (
                    key.lower() in KEYS | IDENTIFIER_KEYS
                    and isinstance(child, str)
                    and child.strip()
                ):
                    self.values.add(child.strip())
                self.learn(child)
        elif isinstance(value, list):
            for child in value:
                self.learn(child)
        elif isinstance(value, str):
            self.values.update(identifier_values(value))
            for match in SECRET.finditer(value):
                self.secrets.add(match[2].strip().strip("\"'"))
            self.values.update(labeled_values(value, LABEL))
            for match in NAMED_PERSON.finditer(value):
                self.values.add(next(group for group in match.groups() if group))

    def token(self, value):
        """为相同敏感值复用占位符，映射不写入日志或发送数据"""
        if "\n" in value or "\r" in value:
            return "".join(
                part if not part or part.startswith(("\r", "\n")) else self.token(part)
                for part in re.split(r"(\r\n|\r|\n)", value)
            )
        if value not in self.mapping:
            self.mapping[value] = f"[[RM_{self.prefix}_{len(self.mapping) + 1}]]"
        self.count += 1
        return self.mapping[value]

    def text(self, value):
        """先移除凭据再替换已知值和常见身份格式，编码附件直接拦截"""
        if TOKEN.search(value):
            registered = set(self.mapping.values())
            parts, offset = [], 0
            for match in TOKEN.finditer(value):
                if match[0] not in registered:
                    raise ProviderError("输入含未知隐私占位符，请使用原始本地资料。")
                parts.extend([self.text(value[offset : match.start()]), match[0]])
                offset = match.end()
            return "".join(parts) + self.text(value[offset:])
        if BLOB.search(value):
            raise ProviderError("隐私保护已拦截编码附件或长编码文本，请移除后重试。")
        value = re.sub(
            r"-----BEGIN [^-]*PRIVATE KEY-----[\s\S]*?-----END [^-]*PRIVATE KEY-----",
            lambda match: "[凭据已移除]" + "\n" * match[0].count("\n"),
            value,
        )

        def secret(match):
            """凭据仅用于本轮删除，不允许通过响应还原"""
            self.secrets.add(match[2])
            self.count += 1
            return match[1] + "[凭据已移除]"

        value = SECRET.sub(secret, value)
        value = re.sub(r"\bsk-[A-Za-z0-9_-]{16,}\b", "[凭据已移除]", value)
        for secret_value in sorted(self.secrets, key=len, reverse=True):
            if secret_value:
                value = value.replace(secret_value, "[凭据已移除]")
        candidates = set(self.values)
        candidates.update(known_variants(value, self.values))
        for candidate in self.values:
            candidates.add(json.dumps(candidate, ensure_ascii=True)[1:-1])
            candidates.add(quote(candidate, safe=""))
        candidates.update(formatted_values(value, PATTERNS))
        spans = identifier_spans(value)
        if candidates:
            pattern = re.compile(
                "|".join(literal_pattern(v) for v in sorted(candidates, key=len, reverse=True) if v)
            )
            spans.extend((match.start(), match.end()) for match in pattern.finditer(value))
        merged = []
        for start, end in sorted(spans):
            if merged and start < merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))
        parts, offset = [], 0
        for start, end in merged:
            parts.extend([value[offset:start], self.token(value[start:end])])
            offset = end
        return "".join(parts) + value[offset:]

    def protect(self, value, *, fixed_keys=()):
        """逐个处理 JSON 字符串，避免转义或字典键绕过替换"""
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, list):
            return [self.protect(child) for child in value]
        if isinstance(value, dict):
            return {
                key if key in fixed_keys else self.text(key): (
                    "[凭据已移除]" if SECRET_KEY.fullmatch(key) else self.protect(child)
                )
                for key, child in value.items()
            }
        return value

    def protect_schema(self, value):
        """保留程序生成契约的固定语法，仅脱敏说明和动态候选中的资料"""
        if isinstance(value, list):
            return [self.protect_schema(child) for child in value]
        if isinstance(value, dict):
            result = {}
            for key, child in value.items():
                if key in {"title", "description", "enum", "const", "examples", "default"}:
                    result[key] = self.protect(child)
                elif key in {"properties", "$defs"}:
                    result[key] = {
                        name: self.protect_schema(definition) for name, definition in child.items()
                    }
                else:
                    result[key] = self.protect_schema(child)
            return result
        return value

    def prompt(self, value):
        """解析末行上下文 JSON 后脱敏，其他提示词按普通文字处理"""
        if "[[RM_" in value:
            raise ProviderError("输入含隐私占位符，请使用原始本地资料重新发起请求。")
        head, separator, tail = value.rpartition("\n")
        try:
            context = json.loads(tail)
        except ValueError:
            self.learn(value)
            return self.text(value)
        if not isinstance(context, (dict, list, str)):
            self.learn(value)
            return self.text(value)
        self.learn(context)
        self.learn(head)
        protected = self.protect(context, fixed_keys={"source_materials", "output_schema"})
        if isinstance(context, dict) and isinstance(context.get("source_materials"), dict):
            source = context["source_materials"]
            # 仅保留本机材料清单的固定路由字段，路径、正文及未知字典键继续脱敏
            protected["source_materials"] = self.protect(
                source, fixed_keys={"files", "limited", "omitted", "notice", "mode", "sources"}
            )
            if source.get("mode") == "on-demand":
                protected["source_materials"]["mode"] = "on-demand"
                protected["source_materials"]["sources"] = [
                    identifier
                    if isinstance(identifier, str) and re.fullmatch(r"source-\d+", identifier)
                    else self.protect(identifier)
                    for identifier in source.get("sources", [])
                ]
            if "files" in source:
                protected["source_materials"]["files"] = [
                    self.protect(row, fixed_keys={"source", "path", "line_start", "text"})
                    for row in source["files"]
                ]
        if isinstance(context, dict) and isinstance(context.get("output_schema"), dict):
            protected["output_schema"] = self.protect_schema(context["output_schema"])
        return self.text(head) + separator + json.dumps(protected, ensure_ascii=False)

    def restore(self, value):
        """单次替换响应占位符，拒绝模型编造的未知标识"""
        reverse = {token: original for original, token in self.mapping.items()}

        def replace(match):
            """仅还原本轮登记且不是凭据的值"""
            if match[0] not in reverse:
                raise ProviderError("模型返回了未知隐私占位符，结果未采用，请重试。")
            original = reverse[match[0]]
            for secret_value in sorted(self.secrets, key=len, reverse=True):
                if secret_value:
                    original = original.replace(secret_value, "[凭据已移除]")
            return original

        if isinstance(value, str):
            clean = TOKEN.sub("", value)
            if "[[RM_" in clean:
                raise ProviderError("模型返回了损坏的隐私占位符，结果未采用。")
            return TOKEN.sub(replace, value)
        if isinstance(value, list):
            return [self.restore(child) for child in value]
        if isinstance(value, dict):
            return {self.restore(key): self.restore(child) for key, child in value.items()}
        return value
