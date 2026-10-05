"""插件拥有的工作台查询贡献"""


def honors(conn, state):
    """在同一读取事务同步已核对的荣誉和简历"""
    from resume_maker.plugin_packages.ext_honors.services.honor_links import honor_sources

    state["honors"] = honor_sources(conn)
