"""招聘收藏夹的可交换文件、链接校验和导入合并规则"""

from typing import Annotated, Literal

from pydantic import (
    Field,
    HttpUrl,
    StringConstraints,
    TypeAdapter,
    field_validator,
    model_validator,
)

from resume_maker.domain.models import Model

Identifier = Annotated[str, StringConstraints(pattern=r"^[a-zA-Z0-9_.:-]{1,100}$")]
Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
HTTP_URL = TypeAdapter(HttpUrl)


class RecruitmentPreferences(Model):
    """收藏夹导入偏好独立保存在本机，不随网址交换文件传递"""

    import_policy: Literal["keep", "update"] = "keep"


class RecruitmentGroup(Model):
    """用户自行维护的领域或分类，稳定标识允许改名后继续导入"""

    id: Identifier
    name: Label


class RecruitmentLink(Model):
    """一个收藏条目中的命名网址，只允许浏览器打开网页"""

    label: Label
    url: str = Field(max_length=4096)

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        """校验网页协议和主机，拒绝凭据及控制字符并统一网址格式"""
        value = value.strip()
        if any(ord(char) < 32 for char in value):
            raise ValueError("网址不能包含控制字符")
        parsed = HTTP_URL.validate_python(value)
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("网址不能包含账号或密码")
        return str(parsed)


class RecruitmentBookmark(Model):
    """企业或自定义招聘网站，可保存多个入口和个人备注"""

    id: Identifier
    name: Label
    domain_id: Identifier | Literal[""] = ""
    category: Identifier | Literal[""] = ""
    description: str = Field(default="", max_length=2000)
    tags: list[Label] = Field(default_factory=list, max_length=30)
    notes: str = Field(default="", max_length=10000)
    favorite: bool = False
    links: list[RecruitmentLink] = Field(min_length=1, max_length=30)


class RecruitmentFile(Model):
    """独立于本机保存版本的 JSON 交换格式，数组顺序即展示顺序"""

    format: Literal["resume-maker.recruitment-bookmarks"]
    schema_version: Literal[1]
    domains: list[RecruitmentGroup] = Field(max_length=100)
    categories: list[RecruitmentGroup] = Field(max_length=100)
    bookmarks: list[RecruitmentBookmark] = Field(max_length=3000)

    @model_validator(mode="after")
    def validate_references(self):
        """整份校验标识、领域名称和引用，防止部分导入留下孤立条目"""
        for groups, label in ((self.domains, "领域"), (self.categories, "分类")):
            if len({group.id for group in groups}) != len(groups):
                raise ValueError(f"{label} ID 不能重复")
            if len({group.name.casefold() for group in groups}) != len(groups):
                raise ValueError(f"{label}名称不能重复")
        if len({item.id for item in self.bookmarks}) != len(self.bookmarks):
            raise ValueError("收藏 ID 不能重复")
        if any(
            item.domain_id and item.domain_id not in {g.id for g in self.domains}
            for item in self.bookmarks
        ):
            raise ValueError("收藏引用了不存在的领域")
        if any(
            item.category and item.category not in {g.id for g in self.categories}
            for item in self.bookmarks
        ):
            raise ValueError("收藏引用了不存在的分类")
        return self


def empty_recruitment() -> RecruitmentFile:
    """创建完全空白的收藏夹，分组和网址由用户添加或导入"""
    return RecruitmentFile(
        format="resume-maker.recruitment-bookmarks",
        schema_version=1,
        domains=[],
        categories=[],
        bookmarks=[],
    )


def merge_groups(current: list[RecruitmentGroup], incoming: list[RecruitmentGroup]):
    """按 ID 或名称复用分组，保留本机名称并返回引用映射"""
    groups = list(current)
    by_id = {group.id: group for group in groups}
    by_name = {group.name.casefold(): group for group in groups}
    mapping = {}
    for group in incoming:
        match = by_id.get(group.id) or by_name.get(group.name.casefold())
        if match is None:
            groups.append(group)
            by_id[group.id] = group
            by_name[group.name.casefold()] = group
            match = group
        mapping[group.id] = match.id
    mapping[""] = ""
    return groups, mapping


def merge_recruitment(
    current: RecruitmentFile, incoming: RecruitmentFile, policy: Literal["keep", "update"]
) -> tuple[RecruitmentFile, dict]:
    """合并文件携带的领域和分类，按稳定标识处理重复收藏"""
    domains, domain_mapping = merge_groups(current.domains, incoming.domains)
    categories, category_mapping = merge_groups(current.categories, incoming.categories)
    bookmarks = {item.id: item for item in current.bookmarks}
    changes = []
    counts = {
        "added": 0,
        "updated": 0,
        "skipped": 0,
        "domains_added": len(domains) - len(current.domains),
        "categories_added": len(categories) - len(current.categories),
    }
    for item in incoming.bookmarks:
        mapped = item.model_copy(
            update={
                "domain_id": domain_mapping[item.domain_id],
                "category": category_mapping[item.category],
            }
        )
        previous = bookmarks.get(item.id)
        if previous is None:
            action = "added"
        elif policy == "keep" or previous == mapped:
            action = "skipped"
        else:
            action = "updated"
        counts[action] += 1
        changes.append({"name": item.name, "action": action})
        if action != "skipped":
            bookmarks[item.id] = mapped
    merged = RecruitmentFile(
        format=current.format,
        schema_version=1,
        domains=domains,
        categories=categories,
        bookmarks=list(bookmarks.values()),
    )
    return merged, {**counts, "changes": changes}
