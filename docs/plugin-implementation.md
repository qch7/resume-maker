# 插件化改造与验收

分支：`codex/plugin-architecture`；改造基线：`e715e2d`。参考实现为 deepseek-harness 的 `5badb15009`。

本分支实现了可运行的本地插件宿主、现有能力的插件组合及外部包入口。最小产品可独立制作简历，标准组合保留原有能力。**它还没有达到[完整目标架构](plugin-architecture-proposal.md)的全部条件**；第 6 节列出差距，不能把通过回归或已有清单解释为这些项目已经完成。完整目标保留，不以实施顺序缩减设计。

## 1. 使用方式

首次启动默认 standard，包含 41 个插件定义。minimal 包含 18 个系统插件和 5 个本地提供方，共 23 个；隐私、sandbox、执行、凭据、任务、草稿和备份仍在其中。没有 AI、OCR、PDF 恢复及 Word 时，手工经历、不可变版本、资料编排、内容预览和 DOCX 导出仍可使用。

```sh
uv run resume-maker --profile minimal --data-dir ./output/manual-demo
uv run resume-maker --profile standard --data-dir ./output/standard-demo
```

已有资料日常切换请使用顶部“插件管理”：选择最小/标准组合或勾选插件，查看变更计划，再保存所有窗口草稿并应用。系统插件不能取消选择，缺少必要提供方或消费者依赖时明确拒绝。`--profile` 是显式启动覆盖；不指定时继续使用该数据目录保存的组合。

外部预构建 `.rmp` 可在管理界面检查、安装和启用，无需修改 App 或重新构建主应用。安装、运行选择和资料保留是独立状态。当前 SDK 和示例见[插件开发协议](plugin-sdk.md)。

## 2. 实际模块边界

| 领域 | 已落实的边界 | 主要位置 |
| --- | --- | --- |
| 清单和组合 | 清单、版本区间、服务基数、明确提供方、Host/Client/remote 分域依赖 | `sdk/manifest.py`、`runtime/graph.py`、`plugins/manifests/`、`plugins/profiles.json` |
| 运行时 | 候选注册、作用域回收、失败回滚、依赖资源保护及实际状态 | `runtime/host.py` |
| 变更协调 | 计划摘要、代次、窗口确认、请求/任务排空、持久提交和路由快照 | `runtime/manager.py`、`runtime/state.py`、`api/plugin_dispatch.py` |
| 系统装配 | 插件入口按声明消费和贡献服务，不在应用工厂建立万能业务容器 | `plugins/system.py`、`providers.py`、`features.py` |
| 业务所有权 | 经历/修订归 Catalog，简历和固定引用归 Resumes，会话和建议采用归 Conversations | `services/catalog.py`、`resumes.py`、`conversations.py`、`sdk/services.py` |
| 查询 | 同一事务读取系统状态，扩展通过查询贡献追加结果 | `services/workspace.py`、`plugins/queries.py` |
| 后台任务 | AI、荣誉识别和模板分析复用执行器；调度意图和输入同事务保存 | `infrastructure/task_supervisor.py`、领域任务服务 |
| 内容隐私 | 网关拥有脱敏、图片保护、敏感值登记和本机还原；传输适配独立 | `integrations/privacy_gateway.py`、privacy 系列 |
| 执行隔离 | sandbox 签发授权，execution 执行，平台后端管理进程树和实际结束 | `infrastructure/execution.py`、`integrations/providers/process.py` |
| 凭据 | 不透明引用、受限借用和撤销，最小系统无需模型登录 | `infrastructure/credential_vault.py` |
| 数据和附件 | SQLite v7、v6 备份迁移、持久所有权目录册、资源发布/租约/墓碑/回收计划 | `infrastructure/data_catalog.py`、`assets.py`、`storage.py` |
| 文档 | 冻结输入，DOCX 引擎和渲染器注册表，预览/导出共用契约，历史成品追溯 | `sdk/documents.py`、`services/document_registry.py`、`document_inputs.py` |
| 外部包 | 摘要和信任检查、不可变安装目录、卸载保留资料、离线 wheel 独立环境 | `runtime/packages.py`、`environments.py` |
| 外部执行 | Host 服务、worker JSON RPC、共享 React ESM、隔离 iframe 消息桥 | `runtime/worker.py`、`frontend/src/plugins/` |
| 客户端 | 壳处理页面和窗口控制；组件、设置页、样式和客户端服务随插件注册 | `frontend/src/app/`、各 feature 的 `plugin.ts` |

手工荣誉字段及既有荣誉快照的展示/同步规则位于简历系统的 `features/profile/honors/`，关闭荣誉库不影响手工内容。制作指引计算位于可选工作流组件中，最小组合不执行它。日志采集和配置属于 sys.activity，日志浏览页面属于 ext.activity-ui。

## 3. 保护和故障语义

- 系统身份由发行策略决定，外部包不能自行声明成系统插件或抢占保留路径。缺系统插件、必要提供方、冲突服务或不兼容接口时不进入 ready。
- 配置计划固定所选集合、版本、包摘要和代次。旧窗口写请求拒绝；离线窗口必须显式保留恢复副本，超时不表示草稿已保存。
- 管理控制通道保持可用，不被它自己参与的业务排空冻结。sys.plugins 重建复用 Host 的唯一协调器，保留计划、窗口和路由发布回调；RPC 按实际扩展所有者取得业务租约。
- 取消直到处理器和清理实际结束才释放租约。调度器拒绝、终态写入失败、重启中断都有可见状态，迟到结果不能发布。
- 执行授权绑定命令、工作目录、环境、材料摘要、所有者代次和有效期，仅能使用一次。Windows 进程挂起创建、加入 Job Object 后再恢复。默认提供方不声称具有 OS 文件/网络强隔离，无法提供的保证明确拒绝。
- 隐私规则变更取消旧上下文，初始材料和后续来源工具均经过保护。OCR/图片处理失败不得发送原图。凭据、进程环境和实际私人资料不进入测试产物。
- 普通保存保留未知扩展资料；缺少解释器时导出要求明确的纯文本展示或隐藏标志。插件停用、卸载和缺包恢复不自动删除资料。
- 数据迁移停机执行，先备份、后在候选库转换。可选插件 schema 不兼容时保留期望选择并阻断其消费者，系统手工功能继续可用。
- 资源先暂存，再在业务事务发布引用。解除引用同事务完成；无引用、无租约才能建立墓碑。停机回收计划只处理超出保留期的失败暂存/墓碑/孤立目录，复核整个计划后才删除，和备份共用写锁。

## 4. 验收范围和证据

测试仅使用合成资料、临时目录及可控模型替身。没有调用真实模型供应商，没有改写用户正式数据。

| 项目 | 已取得的结果 | 本机证据 |
| --- | --- | --- |
| 改造前基线 | 后端 941 passed、12 skipped | 初始基线记录 |
| 最终全量检查 | 后端 1006 passed、12 skipped；前端 175 passed，质量/格式/类型/生产构建通过 | `output/plugin-verified-final.log` |
| 前端 | 175 passed，类型、格式、质量及生产构建通过 | `output/plugin-frontend-refactor-check2.log`、`plugin-ui-release-build.log` |
| 逐项组合 | 每个非系统条目移除均验证依赖拒绝或系统手工/DOCX 闭环；组合用例 32 passed | `output/plugin-composition-matrix.log` |
| 整套组合往返 | HTTP 标准→最小→标准→最小，确认通道、连续路由发布及代次有效；相关回归 38 passed | `output/plugin-profile-roundtrip.log` |
| wheel | 构建成功；安装资源及真正的基础依赖 venv 验证通过 | `output/plugin-wheel-release-build.log`、`plugin-wheel-release-check.log` |
| 物理最小安装 | 无 PIL、PyMuPDF、pdf2docx、RapidOCR、httpx、pytest，完成手工经历→修订→简历→DOCX→ZIP→恢复→再次导出 | `scripts/wheel_minimal.py` 的执行结果 |
| 原生 CLI | 对本机假 Responses 服务验证普通模型/GPT-5.5/GPT-6-Astra及受控图片组合，6 passed | `output/plugin-native-cli-final.log` |
| 实际 Word | 注册表路径下正式导出及临时预览均 1 页、无 render_error；分页图已人工查看 | `output/plugin-word-registry/report.json`、`page-1.png` |
| 外部代码 | 实际包安装后 Host/React、worker 返回 42、独立环境 worker 返回 42、隔离 iframe 返回 42且父页面访问被阻止 | `tests/plugins/test_packages.py`、`output/playwright/plugin-final-rpc.yml`、`plugin-final-isolated-rpc.yml` |
| 外部文档引擎 | 不改主工程安装新的 DOCX 引擎，预览/导出成功；停用后拒绝重新生成，历史文件可下载 | `tests/plugins/test_packages.py` |
| 真实浏览器闭环 | 手工项目→保存 r2→固定简历引用→资料→DOCX；备份恢复后再次导出包含保存内容 | `output/plugin-browser-restore-report.json` |
| 多窗口 | 第二窗口未提交草稿先刷新再确认；切换后恢复草稿，固定修订仍为 r2 | `output/playwright/plugin-final-two-window.png`、`plugin-window2-recovered.yml` |
| 最小/标准界面 | 标准设置贡献、来源扫描快捷入口；最小组合可手工录入并保存荣誉条目 | `output/playwright/plugin-standard-import-shortcut.yml`、`plugin-release-minimal.yml`、`plugin-minimal-manual-honor.yml` |

以上 output 路径为本机忽略的合成验收产物，不进入 Git。可复现用例位于 `tests/plugins/`、原有领域测试和 `frontend/tests/`。真实 Word 和原生 CLI 是单独执行的验收，不能用单元测试中的替身结果代替。默认跳过项中包括需要专门环境的原生 CLI 场景；Linux/Windows CI 状态以 PR 为准。

复盘中修复了来源分页反复读取隐私版本导致的超时、Windows 荣誉附件清理与结束标志之间的竞态，以及整套组合切换冻结管理通道的问题，没有通过延长断言等待或删去场景掩盖失败。

## 5. 数据升级和审查重点

数据库 v6 升到 v7 前保留原库，仅增补插件资料目录册。既有表和路径继续兼容，不为改目录搬动用户原件。导出新增资源索引和引擎追溯字段；历史导出读取继续兼容旧文件。

审查优先检查：系统依赖闭包、管理控制通道、清理失败的依赖保护、任务持久意图和实际租约、隐私策略换代、来源材料权限、版本/草稿冲突，以及备份恢复后的缺插件状态。安装受信任 Host 或 React 代码意味着授予对应宿主权限，清单不能替代 OS 权限隔离。

## 6. 完整目标尚未达标的部分

以下保持在完整设计范围内，本次不能宣称已经实现：

1. **通用多实例容器。** 当前每本地 Host、每定义一个实例；任务级实例及 multiple 明确拒绝。尚无按 application/workspace/task 选择多实例、独立配置及实例间服务绑定的完整容器。
2. **全部公开扩展点。** 页面、设置、组件、服务、查询和文档引擎已可贡献；通用命令/快捷键、自定义字段编辑器、来源贡献、工作流步骤/状态贡献及完整文档导入器注册协议尚未全部形成可独立发布 SDK。外部页面和 RPC 不能替代这些契约。
3. **彻底的内部实现隔离。** API 已使用公开领域 Protocol；存储/事务及部分基础设施还依赖 SQLite 和具体对象。混合路由文件仍按端点归属注册；静态检查覆盖分层、runtime 和 SDK 方向，尚不是覆盖每个插件内部路径的完整导入图门禁。
4. **所有资料统一进入资源后端。** 新成品使用 assets；历史模板、荣誉、证据目录依然由持久描述保护。首次建库仍包含内置插件的完整表集合。成品保留历史目录和 assets 两份文件，尚未进行带迁移验收的去重归并。
5. **完整升级运维。** 本地包、不可变环境和停机资料迁移已存在；尚无自动候选 Host 健康监督/失败回切、在线下载适配、安装进度取消，以及版本固定/联合升级/提供方选择的完整交互。当前 Host 更新要求明确重启。

因此该分支可用于验证和审查本地插件化的运行结果；在以上边界闭合前，应保持 Draft PR，不标记“完整插件化完成”，不自动合并 main。
