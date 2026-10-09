# 独立笔记插件示例

把本目录复制到任意项目外目录，在安装了 Resume Maker 的环境中执行：

```sh
python build.py /absolute/path/notes.rmp
```

SDK 1.1 起也可直接运行 `plugin-sdk validate ./notes-plugin` 和 `plugin-sdk package ./notes-plugin /absolute/path/notes.rmp`，再用 `plugin-sdk test /absolute/path/notes.rmp` 在独立临时宿主验收安装及启停。原标准库构建脚本仍可使用。

在插件管理中检查这个包、确认信任并安装，创建 `community.first`、`community.second` 两个实例，插件定义都选择 `community.notes`。每个实例都有自己的标题配置、笔记页面和持久资料；停用再启用后资料继续保留。

Python 入口只导入 `resume_maker.sdk.context.Context`，前端复用宿主公开的 `/shared/react.js`。构建只使用 Python 标准库，不需要仓库路径或 `tests.support`。代码适配当前 SDK 草稿，发布插件时应固定兼容版本。

`package-plan.json` 是联合升级 API 的请求示例。把 path 替换为包的绝对路径、digest 替换为检查接口返回的摘要、generation 替换为能力清单的当前代次，然后提交到 `POST /api/plugins/packages/plans`。外层字段名为 `packages`。

仓库的 `scripts/check_wheel.py` 会将本目录复制到仓库外，在仅安装 wheel 基础依赖的环境构建包，通过官方启动器和 HTTP 检查安装、自定义实例、实际 JS 下载、RPC、停用、再次启用及重启后的资料恢复。
