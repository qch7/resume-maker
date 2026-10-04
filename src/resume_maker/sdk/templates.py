"""可替换的模板分析策略协议，所有模型出口仍由系统隐私网关提供"""

from typing import Protocol


class TemplateRecords(Protocol):
    """模板库使用所有者的公开仓库，共享调用方事务但不查询私有表"""

    def list(self, conn, excluding=None):
        """列出固定快照中的模板记录"""
        ...

    def get(self, conn, identifier):
        """查询模板或报告记录不存在"""
        ...

    def rename(self, conn, identifier, name):
        """同事务更新模板名称及稳定引用"""
        ...

    def delete(self, conn, identifier):
        """在维护调用方已核验引用后删除模板记录"""
        ...


class TemplateAnalysis(Protocol):
    """拥有分析算法及相应缓存，任务调度和结果发布由模板服务负责"""

    def analyze(
        self,
        package,
        provider,
        workspace,
        document,
        projects,
        settings,
        flag,
        emit,
        initial=None,
        feedback="",
    ):
        """通过已注入的隐私出口分析映射，取消后不得发布结果"""
        ...

    def cache_path(self, directory, package, document, projects, settings):
        """固定当前算法、输入及模型配置的缓存身份"""
        ...

    def cached_plan(self, path, package, document, projects):
        """读取后重新核验缓存是否覆盖当前资料"""
        ...

    def remember_plan(self, path, plan):
        """保存可以重建的已核验分析结果"""
        ...
