"""按明确贡献标识选择文档引擎，缺失或冲突时保留输入并报告原因"""

from resume_maker.core.errors import Problem
from resume_maker.sdk.documents import DocumentEngine, DocumentRenderer
from resume_maker.sdk.imports import DocumentImporter
from resume_maker.sdk.manifest import compatible
from resume_maker.services.document_imports import ImporterRegistry


class DocumentRegistry(ImporterRegistry):
    """注册表每次调用读取当前代次的贡献，实例作用域负责撤销"""

    def __init__(self, contributions, provenance=None):
        """注入通用贡献查询，文档流程不导入具体插件"""
        self.contributions = contributions
        self.provenance = provenance or (lambda _owner: {})

    def entries(self, point, expected):
        """校验声明和实际接口，并保留贡献所有者用于追溯"""
        result = {}
        for item in self.contributions(point):
            if (
                not item.identifier.startswith(item.owner + "/")
                or item.identifier in result
                or not isinstance(item.value, expected)
                or not compatible(
                    item.value.api_version if expected is DocumentImporter else item.value.version,
                    ">=1.0.0 <2.0.0",
                )
            ):
                raise Problem(f"文档贡献协议无效：{item.owner}/{item.identifier}", 409)
            result[item.identifier] = item
        return result

    def engine(self, identifier=None, *, template=False):
        """默认绑定官方引擎，其他提供方只有被明确选择后才接管生成"""
        identifier = identifier or (
            "ext.template-adapter/default" if template else "sys.docx/default"
        )
        item = self.entries("documents.engines", DocumentEngine).get(identifier)
        if item is None:
            raise Problem(f"文档引擎未启用：{identifier}，请启用后重试，已有资料仍保留。", 409)
        if item.value.accepts_template != template:
            raise Problem("所选文档引擎不接受当前模板输入，请明确选择兼容引擎。", 409)
        return item

    def renderer(self, identifier=None):
        """明确选择的渲染器缺失时报错，默认 Word 未启用则保留 DOCX 输出"""
        entries = self.entries("documents.renderers", DocumentRenderer)
        item = entries.get(identifier or "ext.word/default")
        if identifier and item is None:
            raise Problem(f"文档渲染器未启用：{identifier}", 409)
        return item

    def describe(self):
        """公开可选引擎及渲染器，不把内部可调用对象传递到客户端"""
        return {
            label: [
                {"id": item.identifier, "owner": item.owner, "version": item.value.version}
                for item in self.entries(point, expected).values()
            ]
            for label, point, expected in (
                ("engines", "documents.engines", DocumentEngine),
                ("renderers", "documents.renderers", DocumentRenderer),
            )
        }
