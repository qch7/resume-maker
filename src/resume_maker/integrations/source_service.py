"""源码插件公开服务，扫描、只读材料和证据核对统一随插件启停"""

from resume_maker.integrations.source_context import source_context
from resume_maker.integrations.sources import (
    capture_evidence,
    check_evidence,
    project_sources,
    scan_collection,
)


class SourceService:
    """只持有公开经历接口和资源服务，不读取其他业务对象内部状态"""

    def __init__(self, catalog, directory, *, assets):
        """经历服务负责发布证据，资源服务负责读取不可变原件"""
        self.catalog, self.directory, self.assets = catalog, directory, assets

    def scan(self, path):
        """扫描用户明确选择的目录"""
        return scan_collection(path)

    def describe(self, project):
        """只解析当前项目绑定的来源"""
        return project_sources(project)

    def context(self, sources, cancelled):
        """生成有界只读材料工具的上下文"""
        return source_context(sources, self.directory, cancelled)

    def capture(self, project, sources, references, cancelled):
        """核对后交给经历公开事务接口发布不可变证据"""
        return capture_evidence(
            self.directory,
            project,
            sources,
            references,
            cancelled,
            publish=self.catalog.publish_evidence,
        )

    def check(self, snapshot, evidence):
        """按留存原件核对引文，缺证据时明确降级"""
        return check_evidence(snapshot, evidence, assets=self.assets)
