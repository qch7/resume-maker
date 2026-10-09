"""招聘收藏的注册和生命周期入口"""

from resume_maker.plugins.support import dependency, publish, routes


def activate(context):
    """招聘插件拥有业务入口和设置贡献，停用不删除收藏数据"""
    from resume_maker.plugin_packages.ext_recruitment.services.recruitment import Recruitment

    publish(context, "recruitment", Recruitment(dependency(context, "db")))
    routes(context, "resume_maker.plugin_packages.ext_recruitment.routes.recruitment")
    routes(context, "resume_maker.plugin_packages.ext_recruitment.routes.settings")
