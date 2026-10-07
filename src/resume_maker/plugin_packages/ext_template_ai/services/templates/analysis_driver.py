"""模板 AI 插件的分析策略，手工适配器只依赖公开策略协议"""

from resume_maker.plugin_packages.ext_template_ai.configuration import Settings
from resume_maker.plugin_packages.ext_template_ai.services.templates.analysis import analyze_plan
from resume_maker.plugin_packages.ext_template_ai.services.templates.cache import (
    cache_path,
    cached_plan,
    remember_plan,
)


class TemplateAnalysis:
    """模型提示和分析缓存随 AI 插件装配，手工模板核验独立运行"""

    def __init__(self, settings=None):
        """冻结本实例的修正轮数，任务之间不共享可变参数"""
        self.settings = settings or Settings()

    def analyze(self, *args, **kwargs):
        """每轮分析消费同一插件配置快照"""
        return analyze_plan(*args, **kwargs, max_rounds=self.settings.max_analysis_rounds)

    cache_path = staticmethod(cache_path)
    cached_plan = staticmethod(cached_plan)
    remember_plan = staticmethod(remember_plan)
