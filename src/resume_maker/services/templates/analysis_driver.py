"""模板 AI 插件的分析策略，手工适配器只依赖公开策略协议"""

from resume_maker.services.templates.analysis import analyze_plan
from resume_maker.services.templates.cache import cache_path, cached_plan, remember_plan


class TemplateAnalysis:
    """模型提示和分析缓存随 AI 插件装配，手工模板核验独立运行"""

    analyze = staticmethod(analyze_plan)
    cache_path = staticmethod(cache_path)
    cached_plan = staticmethod(cached_plan)
    remember_plan = staticmethod(remember_plan)
