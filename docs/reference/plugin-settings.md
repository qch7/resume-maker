# 插件运行配置

宿主启动变量见 [启动配置](configuration.md)。OCR、Word、日志、数据库和任务的运行参数在所属插件中声明类型、范围和默认值，清单 schema、下表和 [完整示例](../../examples/plugin-config.json) 从同一模型生成。默认配置保持已有行为。

复制示例为自己的 JSON 文件，在 `.env` 中设置 `RESUME_MAKER_PLUGIN_CONFIG=./examples/plugin-config.json`，或使用 `--plugin-config` 指定文件。修改示例不会自动改变已经运行的服务；新进程读取文件后应用配置。示例不包含凭据，实际个人配置不提交到 Git。

配置顺序为清单默认 → 文件中的 bundle → 已保存 workspace → 本次 startup。示例使用名为 `runtime` 的 bundle，值会保存为工作区默认；已保存的界面修改优先。需要本次启动强制覆盖时，把对应操作移到 `startup`。监督器重启沿用保存值，临时 startup 不重复应用。配置文件只能引用已安装的实例；删除可选插件代码后也要删除其配置操作。

例如，只改 OCR 线程数和 Word 等待：

```json
{
  "bundles": [{"name": "local", "edits": [
    {"instance": "provider.rapidocr", "operation": "set", "path": ["intra_op_num_threads"], "value": 4},
    {"instance": "ext.word", "operation": "set", "path": ["render_timeout_seconds"], "value": 120}
  ]}],
  "startup": []
}
```

也可以在“设置 → 插件”编辑所属实例的配置，再查看和应用变更计划。配置变更先排空消费图，再创建使用新快照的实例；取消及关闭失败时保留旧依赖。`sys.plugins` 管理配置需要宿主重启，已有下载和计划沿用创建它们的策略。日志服务重建会按新保留策略清理旧记录，缩短保留天数前应先导出需要的日志。回收站重建也会补做过期清理。

`replace` 替换整份对象，省略的可选顶层字段采用 schema 的默认值，来源显示为 `default`；`set` 修改单字段；`reset` 恢复低一层。未知字段、错误类型、越界值在执行插件代码前拒绝。旧版本保存的空配置可沿用这些默认值。

OCR 的引擎输出门槛 `text_score` 和隐私复核门槛属于不同职责。隐私出口对不确定文字的保护、上传页数和解包上限集中在代码策略中，不能通过配置放宽。当前 OCR 使用随包本地模型，不需要云端地址或 API key。模型名称、思考强度、CLI 路径和模型请求超时继续通过现有模型设置管理。

<!-- BEGIN GENERATED SETTINGS -->

| 插件 | 字段 | 默认值 | 范围 | 用途 |
| --- | --- | --- | --- | --- |
| `ext.ai-conversation` | `close_timeout_seconds` | `8.0` | 1 … 300 | 经历任务关闭等待秒数 |
| `ext.ai-conversation` | `queue_poll_seconds` | `0.5` | 0.1 … 10 | 独立队列检查间隔秒数 |
| `ext.ai-conversation` | `event_poll_seconds` | `0.5` | 0.1 … 10 | 进度流检查间隔秒数 |
| `ext.honors` | `close_timeout_seconds` | `10.0` | 1 … 300 | 荣誉任务关闭等待秒数 |
| `ext.provider-codex` | `inspection_timeout_seconds` | `15.0` | 1 … 120 | CLI 版本探测秒数 |
| `ext.source-code` | `git_timeout_seconds` | `20.0` | 1 … 120 | 只读 Git 查询等待秒数 |
| `ext.template-adapter` | `close_timeout_seconds` | `8.0` | 1 … 300 | 模板任务关闭等待秒数 |
| `ext.template-ai` | `max_analysis_rounds` | `3` | 1 … 8 | 最多模型分析和修正轮数 |
| `ext.template-library` | `trash_retention_days` | `30` | 1 … 3650 | 回收站保留天数 |
| `ext.template-library` | `trash_sweep_seconds` | `60.0` | 10 … 86400 | 清理检查间隔秒数 |
| `ext.word` | `render_timeout_seconds` | `90.0` | 5 … 600 | Word 执行秒数 |
| `ext.word` | `close_timeout_seconds` | `30.0` | 1 … 300 | Word 关闭等待秒数 |
| `ext.word` | `preview_scale` | `1.3` | 0.5 … 3 | PNG 分页预览栅格倍率 |
| `provider.rapidocr` | `intra_op_num_threads` | `2` | 1 … 16 | 算子内部 CPU 线程数 |
| `provider.rapidocr` | `inter_op_num_threads` | `1` | 1 … 16 | 算子之间 CPU 线程数 |
| `provider.rapidocr` | `detection_side` | `736` | 128 … 4096 | 文本检测最长边像素数 |
| `provider.rapidocr` | `base_side` | `960` | 128 … 2048 | 首次识别最长边像素数 |
| `provider.rapidocr` | `retry_side` | `2000` | 256 … 4096 | 复核识别最长边像素数 |
| `provider.rapidocr` | `text_score` | `0.3` | 0 … 1 | 引擎输出文字的最低置信度 |
| `provider.rapidocr` | `adaptive_retry_enabled` | `true` | — … — | 空白、稀疏或小字页复核一次 |
| `provider.rapidocr` | `small_text_height` | `14.0` | 0 … 64 | 小字复核高度阈值像素数 |
| `provider.rapidocr` | `sparse_result_count` | `2` | 0 … 20 | 稀疏文字复核行数阈值 |
| `provider.rapidocr` | `pdf_render_side` | `2400` | 512 … 4096 | PDF 栅格化最长边像素数 |
| `provider.rapidocr` | `pdf_render_scale` | `3.0` | 1 … 4 | PDF 栅格化最大倍率 |
| `provider.sqlite` | `lock_timeout_seconds` | `10.0` | 0.1 … 60 | SQLite 锁等待秒数 |
| `sys.activity` | `max_records` | `50000` | 100 … 1000000 | 最多保留日志条数 |
| `sys.activity` | `retention_days` | `30` | 1 … 3650 | 日志保留天数 |
| `sys.activity` | `lock_timeout_seconds` | `2.0` | 0.1 … 10 | 日志库锁等待秒数 |
| `sys.jobs` | `max_workers` | `4` | 1 … 32 | 任务执行线程数 |
| `sys.jobs` | `close_timeout_seconds` | `30.0` | 1 … 300 | 任务关闭等待秒数 |
| `sys.jobs` | `owner_close_timeout_seconds` | `30.0` | 1 … 300 | 单个任务所有者的关闭等待秒数 |
| `sys.plugins` | `download_timeout_seconds` | `5.0` | 1 … 60 | 下载网络等待秒数 |
| `sys.plugins` | `download_close_timeout_seconds` | `10.0` | 1 … 120 | 下载取消后的关闭等待秒数 |
| `sys.plugins` | `install_timeout_seconds` | `300.0` | 30 … 1800 | 离线安装秒数 |
| `sys.plugins` | `candidate_timeout_seconds` | `120.0` | 10 … 600 | 候选验收秒数 |
| `sys.plugins` | `plan_lifetime_seconds` | `600.0` | 60 … 3600 | 变更计划有效秒数 |

<!-- END GENERATED SETTINGS -->

新增参数时修改所属 `configuration.py` 并接入实际消费者，执行 `uv run python scripts/sync_plugin_settings.py`。完整检查会验证清单、文档和示例未漂移。配置模型保持纯声明，不能导入可选引擎或读取本机环境。
