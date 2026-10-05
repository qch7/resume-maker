"""荣誉识别的注册和生命周期入口"""

from resume_maker.plugin_packages.ext_honor_recognition.recognition import recognize
from resume_maker.plugins.support import dependency, routes, task_queue


def activate(context):
    """仅选择识别能力时启动荣誉后台线程"""
    service = dependency(context, "honors")
    detach = service.attach_recognition(
        dependency(context, "provider"), task_queue(context), recognize
    )
    context.lifecycle(service.start, detach)
    context.effect(
        dependency(context, "tasks").attach(
            context.instance_id,
            lambda: [
                {"id": row["id"], "state": row["status"]}
                for row in service.list()
                if row["status"] in {"queued", "running"}
            ],
            service.cancel,
        )
    )
    routes(context, "resume_maker.plugin_packages.ext_honor_recognition.routes.honors")
