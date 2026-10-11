# 当前插件开发协议

本文说明当前插件接口、包格式和运行边界。宿主装配及生命周期见 [架构说明](../architecture.md)，开发检查见 [开发指南](../development.md)。

Host 和 Client SDK 当前为 **1.1.0**。使用公开 OCR 类型、凭据字段和可取消请求的插件应声明对应的 `host_api` / `client_api: ">=1.1.0 <2.0.0"`；既有 `>=1.0.0 <2.0.0` 插件继续兼容。服务自身的版本独立维护，`ocr.backend` 和 `credentials` 仍为 1.0.0。

## 本地组合

`plugins/profiles.json` 定义必需身份和发行策略，minimal / standard 成员来自各独立包的 `package.json.resumeMaker.profiles`。18 个系统职责必装，5 个本地提供方补全依赖；标准组合另含 18 个扩展及提供方。系统身份由发行策略判断，第三方不能占用内置 ID。

## 内置代码包和加载流程

所有内置包位于 `src/resume_maker/plugin_packages/<slug>/`。以荣誉库为例，完整实现位于 `ext_honors/`：`manifest.json` 声明能力、依赖及贡献，`package.json` 声明产品组合和客户端构建入口，`entry.py` 注册服务、HTTP 路由及工作台查询，`services/`、`routes/`、`query.py`、`data/` 和 `client/` 保存对应实现。识别策略单独归属 `ext_honor_recognition/recognition.py`，按公开回调附接，删除识别插件仍保留手工荣誉库。系统插件同样遵循这一组织方式。

发现阶段只读取 JSON，不执行插件。Host 求解已选择能力图，按依赖顺序导入清单中的 `entry.py:activate`，并为入口创建作用域。入口调用 `provide` 或 `contribute` 后，服务、路由和查询进入当前代次；未选择的入口不执行。服务通过 SDK Protocol 和声明的能力注入，宿主及其他插件禁止直接导入包内实现。

`frontend/scripts/build-plugins.mjs` 扫描包元数据，把每个客户端分别构建为 `.local/plugin-builds/<slug>/plugin.js`、样式及块，并登记逐文件 SHA-256。wheel 将这些产物带入包内 `client_dist/`。清单使用 `bundled:plugin.js`；能力 API 将其改写为含索引摘要的 `/bundled-plugin-assets/<ID>/<digest>/plugin.js`，客户端按依赖加载该模块并执行注册入口。React 和 SDK 子入口由宿主同一构建图提供，多个包共享 React 实例。

包内客户端通过 `@resume-maker/plugin-sdk/<子入口>` 使用公开控件、hooks、类型及注册 API。新增包不需要编辑宿主导入表、Vite 入口表或导航 ID 清单。`context.workbenchPage` 注册工作台附加页面，`context.navigation` 贡献领域导航，`context.component` 注册公开插槽；所有贡献归属作用域，停用时撤销。`templatePicker` 是模板库贡献，缺包时宿主显示明确的不可用状态。

保留 `frontend/src/shared/` 的可复用资料转换、字段编辑和控件；`integrations/word/` 是文档引擎和导入器共同使用的工具库。实际 RapidOCR 模型位于 `provider_rapidocr/local_ocr.py`，Word 进程和渲染器位于 `ext_word/integrations/word/`，模型 CLI 位于 `ext_provider_codex/integrations/providers/`。共享工具通过注入参数及 `Provider.read_ocr` 消费能力，缺少提供方不会隐式启动插件实现。实现新的 Provider 时须补充 `read_ocr`；荣誉识别附接须传入策略回调。

停机后移除任一可选包目录再构建，无需修改其他代码文件。默认或已保存选择启动时报告缺包并阻断缺依赖的消费者，保留原始选择以便恢复安装；显式 `Config.plugins` 仍严格校验。必需包缺失拒绝启动。代码删除不清理数据库、附件、未知扩展或历史日志；已持久登记的资料描述继续用于备份及隐私保护。运行时停用和安装包卸载仍使用排空、停止屏障及作用域清理协议。

首次默认使用 standard；`--profile minimal` 或 `--profile standard` 可显式指定启动组合。未指定 profile 时优先读取数据目录 `plugins.json`。已有数据上显式指定 profile 会覆盖保存的选择，日常切换应使用插件管理的排空协议。

“设置 → 插件”用卡片显示选择、活动状态及阻断原因，详情中提供配置和安装操作。极简模式对应 minimal，扩展模式对应 standard，并可按需调整开关；模式选择只改变候选，不立即切换运行能力。查看变更计划后，准备阶段刷新所有窗口草稿，确认后等待请求及后台执行结束，最后应用并刷新客户端。未满足硬依赖的候选被拒绝，不自动猜测供应商。

插件列表可切换按模式分类、按能力分类。能力分类根据清单 `capability_groups` 聚合 OCR、日志等领域，同一插件可属于多个领域。整组停用会逐层停用硬依赖消费者；必需插件仍保留，基础职责需要的提供方不可整组关闭。整组启用保留已选择的供应商，缺少依赖时只补齐明确的提供方；多个唯一提供方需要先单独选择。搜索只筛选展示，整组开关始终作用于全部成员。开关只修改候选，继续通过查看变更、应用计划生效，已有资料保留。

`POST /api/plugins/capability-selection` 接受 `{group, enabled, selected, generation, instances?}`，返回补齐依赖或逐层停用后的 `{selected}`。该接口校验窗口代次，不持久化候选、不改变活动组合；实例绑定继续参与依赖校验，配置草稿仍通过原有计划提交。

## 清单及依赖

Python 公共入口在 `resume_maker.sdk`，定义见 `sdk/manifest.py`、`context.py`、`model.py` 和 `services.py`。清单拒绝未知字段，插件版本和协议版本使用稳定 SemVer；Python 分发依赖使用 PEP 440。

```json
{
  "manifest_version": 1,
  "id": "community.example",
  "title": "示例能力",
  "capability_groups": [{"id": "example", "title": "示例领域"}],
  "version": "1.0.0",
  "package": "community.example",
  "entrypoints": {
    "host": {"mode": "trusted-host", "entry": "python/plugin.py:activate"},
    "client": {"mode": "trusted-client", "entry": "client/index.js"}
  },
  "requires": {"host": {"db": ">=1.0.0 <2.0.0"}},
  "provides": {"host": {"example": {"version": "1.0.0", "cardinality": "one"}}},
  "contributes": {"http.routes": ["community.example/routes"]},
  "permissions": ["workspace.trusted"],
  "data": {"settings": ["community.example:"]}
}
```

- `requires.host`、`requires.client` 和 `requires.remote` 分域求解；remote 指向 Host 上的服务，但通过 JSON RPC 访问。
- `capability_groups` 是可选的能力分类列表，每项声明稳定 `id`、显示 `title`。旧提供方省略时沿用相同服务的已声明分类，例如 `ocr.backend` 归入 OCR；其他未声明分类的插件显示在未分类中，不提供整组开关。公共依赖不用于推断领域；分类不改变服务契约、系统必需身份或数据归属。
- 依赖值可以是版本字符串，或 `{version, cardinality, provider}`。集合基数为 `many`，唯一能力为 `one`；多个候选必须明确选择，不能按装载顺序抢占。
- `provides.<域>.<能力>.title` 可声明能力显示名称，例如 `speech.backend: {"cardinality": "one", "title": "语音合成引擎"}`。名称仅用于展示，不参与依赖求解；未声明时使用能力名。
- `optional` 是当前 Host 可选依赖；存在时验证版本并加入激活依赖。
- `enhances` 声明插件给其他服务附接的行为，用于计算重建和排空范围。必须同时声明目标依赖。此影响图允许双向关系，不能拿来做激活拓扑排序。
- `plugins` 约束其他插件的版本；`dependencies` 约束 Python 分发依赖。依赖不满足时不能激活。
- `config_schema` 校验配置；管理界面按字段类型生成独立控件，复杂结构保留 JSON 编辑。计划锁定配置和包摘要，变化后旧计划失效。

服务、贡献和实例代次相互独立。`InstanceSpec {id, plugin, bindings}` 为插件定义创建稳定实例，非默认实例要求 `instances.multiple=true`。提供唯一服务的插件仍不能靠多实例绕过服务基数；集合提供方须明确绑定。插件管理支持创建独立实例、分别编辑配置和选择 Host/Client/remote 提供方，停止或移除实例保留资料。

应用作用域可以拥有多个工作区，工作区可以拥有任务作用域。短生命周期实例能消费父服务，父实例不能依赖任务实例。工作区使用独立数据目录；任务权限不得超过提交者的权限。`PluginContext` 提供 `plugin_id`、`instance_id`、`scope_id` 和独立配置。`context.health(check)` 在发布前检查实际能力，失败回收候选并恢复此前配置。

声明 `storage.instances` 后，`context.data` 提供 `get/set/delete/transaction`，每个键使用 `expected_version` 比较版本。应用和工作区资料按作用域及实例隔离，任务资料只驻留本轮内存。停用后旧句柄失效，持久记录保留；删除记录保留版本墓碑，`null` 是业务值。

任务提交可以携带 `plugin_instances` 和 `plugin_configs`；`sys.jobs` 在入队前固定代码摘要、配置、代次和权限，执行期间通过 `sdk.tasks.current_task().require(instance, ServiceKey(...))` 读取本轮实例。任务取消后等待真实处理和作用域清理结束。清理失败的作用域继续阻止相关插件变更。

### 配置覆盖

内置运行策略的字段及完整示例见 [插件运行配置](plugin-settings.md)。所属 `configuration.py` 的 `Settings(PluginSettings)` 声明类型、默认及边界，入口通过 `Settings.model_validate(context.config)` 冻结实例快照。生成的清单使用 `x-resume-maker-strict` 让候选阶段拒绝布尔冒充数字、浮点冒充整数和非有限数；外部未声明该扩展的 schema 保持 JSON Schema 原有类型规则。

配置顺序为清单默认值、有序 bundle、工作区覆盖、本次启动覆盖。`ConfigurationEdit` 使用 `replace` 替换整份对象，`set` 按属性路径设置，`reset` 恢复该层开始前的继承值；数组整体替换，重置操作不能携带 `value`。管理计划返回有效配置、逐字段来源和摘要，全部通过 schema 校验后才可应用。

替换后缺失的可选顶层属性可以采用其 schema 中声明的默认值，来源标记为 `default`。必填属性仍需明确提供；不递归填充嵌套对象，也不把 JSON Schema 的默认值当作任意深度合并规则。

插件管理的字段表单按 `config_schema` 生成数值、开关、文本和枚举控件，标签优先使用 `description`，其次为 `title` 和字段名。非空嵌套对象展开属性，数组和复杂联合保留单项 JSON，本地 `$ref` 和可空字段得到相应控件；未声明属性的配置仍可通过“高级 JSON”编辑。浏览器检查明确的类型及边界，服务端继续负责完整 schema 校验。

普通字段编辑只发送明确的 `set` 和 `reset`，未编辑字段不转为工作区覆盖。“高级 JSON”是工作区整份替换，字段及整份重置使用独立按钮，计划内显示服务端返回的有效值及来源。`POST /api/plugins/plans` 接受 `config_edits`，例如 `{instance: "community.example", operation: "set", path: ["options", "count"], value: 2}`。`reset` 使用相同路径且省略 value；空路径表示重置整份配置。

`--plugin-config <JSON文件>` 接受 `{bundles: [{name, edits}], startup: [操作...]}`。bundle 按顺序应用并持久保留；startup 只在当前启动生效，普通重启不会把临时值当成永久配置。发行组合也可通过 `profiles.json` 的 `profile_bundles` 及 `bundles` 声明默认配置。文件不执行代码，不包含密钥原文，凭据继续使用独立引用。

## Host 服务、路由及资源

### 外部提供方身份和替换

`sys.*` 和 `provider.*` 为宿主保留身份，外部包及构建前校验均拒绝使用。第三方 OCR 包使用 `community.baidu-ocr` 等自有 ID，提供的能力仍声明为 `ocr.backend`；包身份和服务名分别表达所有者和接口。

“设置 → 插件 → 能力提供方”在一份计划中启用候选、停用冲突的旧提供方，并审查消费者及配置影响。插件卡片的启用开关同样协调唯一能力。显式实例绑定同步替换；清单硬性依赖某个包或固定提供方时仍由求解器拒绝不兼容计划。旧提供方的全部能力一并消失，其他消费者缺依赖时计划失败，活动组合保持原样。`many` 集合能力继续允许多个提供方，不进入唯一能力替换入口。

选择页按能力域及能力名自动分组。已安装的同域唯一能力存在两个以上提供方时显示选择行，新增领域能力无需修改设置页。名称取该组首个非空 `title`，建议同一能力的提供方使用一致名称；同名的 Host、Client 能力分别选择。只有一个提供方时继续通过插件开关启用。

### OCR 契约和合成验收

公开接口位于 `resume_maker.sdk.ocr`：`OCRBackend.read_document(Path, threading.Event) -> OCRDocument`、`OCRPage` 和 `OCRBlock`。返回值保持普通字典，便于原有插件兼容。`pages` 使用原文分页顺序；每行包含非空 `text`、`confidence`（有限的 0..1）和 `box: [x0, y0, x1, y1]`，坐标以原页面左上角为原点，归一化至 0..1 且有正面积。页面 `width` / `height` 为相应坐标页面的尺寸，图片可使用像素、PDF 文字层可使用页面单位；比例坐标不受单位影响。`method` 是提供方的提取方式标识。

文档 `text` 按行 `\n`、页间 `\n\n` 汇总，`seconds` 是非负有限耗时，`needs_review` 至少覆盖置信度低于 `OCR_REVIEW_CONFIDENCE` 的行，`notice` 提供提取及复核说明。空页保留分页和空 `blocks`，整份无文字抛出 `ProviderError`。异常不能包含凭据或原文；取消抛出 `Cancelled`，返回前再次检查信号。实际 HTTP、模型或子进程结束前不得报告停止完成。

SDK 导出统一边界：12 页、100000 字符、6000 行、20 MiB 输入和 4000 万原图像素；当前复核门槛为 0.85。宿主内部复用同一组常量。文件与像素检查由读取原件的提供方执行，`ext.ocr` 在公共消费入口通过 `validate_ocr_document` 统一核验返回值和取消后的结果。图片恢复所用的低层 `recognize` 保持原有私有策略接口。

插件可把合成结果输出为 JSON，执行 `plugin-sdk test --ocr-result synthetic-ocr.json` 验收结构；本地测试也可以直接调用 `validate_ocr_document`。此验收覆盖格式和资源边界，真实图片准确率另行验证。

### 凭据字段和持久引用

`resume_maker.sdk.credentials.Credentials` 公开 `register(adapter, purpose, loader)`、`borrow(reference, adapter, purpose)` 和 `revoke(reference)`。临时加载器注册沿用原行为；持久密码由宿主管理界面保存，插件通过引用借用。声明如下：

```json
{
  "host_api": ">=1.1.0 <2.0.0",
  "requires": {"host": {"credentials": ">=1.0.0 <2.0.0"}},
  "credential_fields": {"api_key": {"title": "API Key", "purpose": "ocr.auth"}},
  "config": {"api_key": ""},
  "config_schema": {
    "type": "object",
    "properties": {"api_key": {"type": "string", "format": "credential-ref"}},
    "additionalProperties": false
  }
}
```

凭据字段目前支持顶层字符串。密码控件初始为空，保存只返回 `cred.<随机身份>`；普通配置、客户端快照和计划只能保存引用，服务端拒绝填入原文。API 日志不采集凭据请求正文和摘要，输入校验也不回显原文。随后在现有计划中应用新引用，当前插件继续使用旧引用。代码借用示例：

```python
from resume_maker.sdk.context import ServiceKey
from resume_maker.sdk.credentials import Credentials

credentials = context.require(ServiceKey[Credentials[str]]("credentials"))
with credentials.borrow(context.config["api_key"], context.instance_id, "ocr.auth") as api_key:
    pass  # 仅在本轮可信适配器调用内使用
```

引用固定到实例和用途，重启后可继续使用；创建新实例需重新配置密钥。Windows 使用当前用户 DPAPI 加密，POSIX 使用 0700 目录和 0600 文件限制访问，不宣称 POSIX 文件加密。密码存放在资料目录的 `credential-vault/`，不进入资料 ZIP 备份；同机恢复保留现有 vault，换机恢复需重新录入。停用和保存新引用保留旧凭据，插件可以显式撤销不再使用的引用，已借用的实际执行仍需结束。已保存但未应用的引用不会自动改变活动配置。

### HTTP 截止、取消和共享配额

声明 `requires.host["http.client"]` 后，通过 `ServiceKey[HTTPClient]("http.client")` 消费 `sdk.http` 契约。同步 `request(method, url, deadline=..., cancelled=..., quota=..., headers=..., body=..., max_bytes=...)` 共用宿主连接池；`deadline` 为 `time.monotonic()` 的绝对截止，覆盖排队、连接和响应。只接受 HTTPS，不继承环境代理、不自动重定向；返回有界的原始响应字节、状态码和头部，供应商格式由插件解释。

同一供应商账户须使用相同 `quota` 键，建议按供应商身份和持久凭据引用组合，不含密码原文。每个键最多四个传输和三十二个等待，宿主总等待及执行最多一百二十八个，配额键最多二百五十六个。此服务提供并发配额协调；供应商的每分钟请求数和计费额度仍需插件按账户策略控制。取消和关闭均等待实际异步传输清理，不能保证已经送达供应商的请求被撤回。模型材料仍须经过隐私网关，这个通用服务不构成隐私授权。

客户端 `context.request(method, payload, signal?)` 现接受 `AbortSignal`，沿用固定代次及 RPC 命名空间。浏览器中止只停止等待及接收结果，服务端任务停止仍由已声明的任务取消接口和实际停止屏障控制。

### 插件作者工具

安装 Resume Maker 后即可使用 `plugin-sdk`，也可执行 `python -m resume_maker.plugins.tools`：

```sh
plugin-sdk validate ./source --include python/helpers.py
plugin-sdk package ./source ./plugin.rmp --include python/helpers.py
plugin-sdk environment-lock ./source ./source/wheels ./source/environment.json
plugin-sdk test ./plugin.rmp --enable ext.ocr
plugin-sdk test --ocr-result ./synthetic-ocr.json
```

`validate` 和 `package` 不执行插件代码，核验身份、SDK 区间、清单、入口、摘要及包资源边界。只收集入口、许可证、声明的资料/锁文件和显式 `--include` 文件，输出文件存在时拒绝覆盖。依赖辅助模块需显式列入，源码目录中的未列入文件不随包发布。

`environment-lock` 从包内 wheel 目录读取 METADATA，按当前解释器平台筛选并核验传递依赖和 extras；Host 插件必须包含 Resume Maker 及其完整运行依赖。缺包或版本冲突直接失败，不能把本机已有库当作离线依赖。工具不下载 wheel，也不修改活动解释器；发布者准备相应平台的二进制 wheel 后，将 `environment_lock` 指向生成文件，再校验并打包。安装预览提供目标解释器及 `uv pip install` 参数数组，Host 依赖准备须停机，不自动补装。

`test` 显式执行受信任插件，在临时资料目录启动独立本机宿主，通过 HTTP 验收安装、启用、停用、再次启用和正常关闭；清除继承的模型凭据，不使用正式资料或 `tests.support`。`--enable` 补充消费者及依赖，整个候选仍须满足求解器。存在独立表迁移的包须先按离线维护流程验收。可复用 `resume_maker.plugins.testing.PluginTestClient` 编写 RPC 和业务断言；默认生命周期冒烟检查不替代插件自己的完整业务测试。

普通编辑的共享写入也需要并发基线。`PUT /api/settings/provider` 使用 `ProviderSettings.version`，成功响应返回本次写入的新版本；旧资料未存版本时从 0 开始，无需数据库迁移。修改 `PATCH /api/conversations/{id}` 的 `input_draft` 时必须同时携带原始 `expected_input_draft`，缺少基线返回 422，基线变化返回 409。仅修改标题、讨论范围或归档状态不需要输入基线。

`POST /api/resumes/{id}/exports?version=<刚保存的版本>` 必须传入方案版本。冻结输入的事务内核对该版本，变化时返回 409 且不发布成品。SDK 的 `Documents.export` 和 `Resumes.freeze_export` 接受 `expected_version`；由用户保存动作触发的调用应传入该值。

临时预览使用 `sdk.previews.PreviewCache`，简历预览和模板试填各保留最多 24 份、总计 128 MiB，按最近使用顺序回收。单份超过预算时拒绝发布，渲染失败的部分产物立即回收。HTTP 下载通过 `LeasedFileResponse` 持有租约直到完整传输结束或断开，所有容量被活动租约占用时等待用户重试。只清理当前实例创建的临时目录，正式导出、模板原件和分析草稿继续按各自资料规则保留。

异步简历预览入口先进入 `ResumePreviews.request_work(cancelled, timeout=...)` 上下文，再提交线程池；上下文固定实例准入、取消事件和绝对截止，并保持到实际工作及清理结束。AnyIO 将上下文复制给工作线程，`render` 沿用原预算，不重复准入或重新计时；直接同步调用 `render` 仍自动建立独立作用域。HTTP 请求拥有监视器和执行子任务，默认每 50 ms 核验截止及断开；请求任务取消也通知同步工作，池外等待可撤销，已开始工作须完成清理后归还容量。渲染器通过 `sdk.documents.current_document_work()` 或 `check_document_work()` 响应同一取消和截止，单个不协作的原生调用仍不能任意抢占。实例默认最多 16 个执行及等待请求、串行生成、总预算 660 秒；每次未命中预览通常生成一份 DOCX 并调用一次渲染器，不增加自动重试。

```python
from fastapi import APIRouter
from resume_maker.sdk.context import ServiceKey


def activate(context):
    """发布服务和命名空间路由，注册会随当前作用域撤销"""
    db = context.require(ServiceKey("db"))
    context.provide(ServiceKey("example"), {"ready": True})
    router = APIRouter()

    @router.get("/api/plugins/community.example/items")
    def items():
        """只读取当前插件的持久设置"""
        return db.setting("community.example:items", [])

    context.contribute("http.routes", "community.example/routes", tuple(router.routes))
```

外部路由必须位于 `/api/plugins/<插件ID>/`。提供和消费都需要清单声明。`effect()` 登记幂等回收，`lifecycle(start, stop)` 在注册验证后启动；执行结束屏障失败时保留资源依赖。回收不能只发取消信号就返回。

入口可标注为 `activate(context: Context) -> None`，公开类型包含配置、服务、贡献、RPC、生命周期及健康检查。`config` 是当前实例的配置副本；`rpc` 的处理函数接收一个载荷，输入输出仍由清单 schema 校验。

切换失败后按实际处于运行中的依赖图清理：旧组合未排空时先重试旧实例，候选已开始激活时清理候选。只有重建旧实例、核验实际服务和发布路由均成功才解除维护；清理仍失败时记录 `recovery-required`，保留依赖并要求停止宿主后重新启动此前组合。

停止顺序使用包含 `consumes` 和 `enhances` 的完整消费图，消费者先于提供方；增强造成的环作为共同排空的组处理。全部受影响实例的 `lifecycle` 停止屏障通过后才进入资源释放，任一屏障失败时本轮不释放资源。动态切换和 `Host.close()` 共用这一流程。

宿主退出先完成本作用域的停止屏障，任务调度器拒绝新任务、通知取消并等待执行及其清理实际结束；之后回收残留子作用域，最后释放父资源。等待子作用域关闭时不占用父容器锁，任务可以自行完成清理，重复 `close_scope()` 安全。停止超时仍保留执行器和资源，旧任务退出后可重试关闭。

应用内业务路由通过 `Depends(service("服务名"))` 显式注入；建立快照时核验所有权。依赖解析只异步查找请求租约内已注册的内存服务，不借用共享线程池，阻塞业务方法仍在工作线程执行。领域方法签名定义在 `sdk/services.py` 的 Protocol 中，HTTP 层不再为类型声明导入对应服务实现。已有 HTTP 路径保持兼容，模块内部的端点分组由插件注册确定。

持久资源使用 `assets.stage(owner, bytes, media_type)`，之后在业务数据库事务内 `assets.publish(conn, staged, references)`。未提交的暂存记录不允许读取；读取通过 `lease()` 保持摘要和生命周期。历史模板、荣誉和证据目录仍由各插件的持久描述枚举，不能以插件停用为由清理它们。

业务删除引用时，在同一事务调用 `assets.release_reference(conn, id, owner, reference)`；没有引用和读取租约后才可 `tombstone(id, owner)`。失败暂存、墓碑及无登记的 UUID 资源目录默认保留至少 24 小时，停机通过 `--asset-gc-plan` 生成精确回收计划，再用 `--asset-gc-apply <文件> --confirm-digest <摘要>` 确认。回收持有备份共用的数据库写锁，复核所有记录和文件摘要后才删除。已发布资源不会因关闭插件或长期未访问而回收。

工作台查询使用 `workspace.queries` 贡献，接收已有读取事务和返回字典。仅依赖事务快照的查询可用 `sdk.storage.database_query` 标记，数据库没有提交且贡献未变时复用聚合；查询若依赖内存、时间或外部状态，不加此标记，保持每轮执行。修改已有简历来源时保留历史确认快照；不要让关闭扩展导致普通保存删去未知内容。

## 文档引擎贡献

`sdk/documents.py` 定义 `DocumentInput`、`DocumentEngine` 和 `DocumentRenderer`。第一版引擎输出可编辑 DOCX，渲染器补充 PDF 和分页。内置版式、模板填充及 Word 分别贡献 `sys.docx/default`、`ext.template-adapter/default`、`ext.word/default`，不再靠改变全局生成函数选择实现。

引擎清单声明 `contributes.documents.engines`，生成入口用 `context.contribute("documents.engines", "当前插件ID/docx", DocumentEngine("1.0.0", generate))` 注册。渲染器使用 `documents.renderers` 和 `DocumentRenderer`。标识须属于贡献者，重复标识和不兼容版本拒绝使用；模板引擎须声明 `accepts_template=True`。外部引擎声明对 `documents` 的依赖及 `enhances`，进入反向排空范围。

`generate(output_path, frozen_input)` 只能消费冻结输入；`frozen_input.values()` 返回独立的简历、项目及模板对象，`template_bytes` 是同一快照中的原件。生成失败或没有输出时不发布成品。预览和导出共用注册表，清单记录选中引擎、渲染器和版本。默认选择保持官方绑定，其他引擎必须明确指定。

`GET /api/document-engines` 列出活动引擎和渲染器；导出及预览接受可选查询参数 `engine_id`、`renderer_id`。引擎停用后重新生成返回明确错误，历史成品仍可下载。现有简历界面沿用默认引擎；外部页面可通过公开 API 提供自己的选择交互。

## 资料来源和补充隐私规则

`sdk/sources.py` 的 `ResumeSource` 注册到 `resume.sources`。`browse(reader, cursor, query, limit)` 返回 `SourcePage`，每页最多 100 条；`resolve(reader, ids)` 只返回明确请求的 `SourceItem`。提供方只发布已核对资料，查询共用简历保存或读取事务的只读快照，不拥有提交权限。

`GET /api/resume-sources` 列出来源，`GET /api/resume-source-items?provider=<贡献ID>` 支持 cursor、query 和 limit。栏目编辑器的“从资料来源添加”直接消费该接口，选择只进入草稿。条目保存 `source: {provider,id,version}`，内容存入原有文字字段，因此缺包后仍能预览和导出。

来源同步只改变所属文字及自定义字段的值和来源版本，简历保留显隐、顺序、手工字段和自定标签。未返回的条目保留原快照；停用前系统固化最后确认内容并递增简历版本，旧草稿仍走冲突检查。来源删除应在同一事务调用公开的 `resume.preserve_sources(conn)`。荣誉库使用相同协议，条目通过 `source.provider = "ext.honors/library"` 及明确的来源 ID 关联，不从条目标识推断来源。

`sdk/privacy.py` 的 `PrivacyRuleContribution` 注册到 `privacy.rule_contributions`。`collect(reader)` 返回 `PrivacyValues(terms, private_data)`，系统引擎追加这些词和结构化身份，规则不获得还原表，也不能撤销基础格式保护。规则需提供版本、标题和本地说明；异常阻止该次模型请求，错误不回显资料正文。规则或词变化会使旧隐私上下文取消。

持久资料的 `data.privacy_settings` 声明需要持续保护的设置前缀，外部插件只能声明自己的命名空间。系统直接读取目录册中的资料，不执行缺失插件代码，因此停用和卸载不会撤销对已存身份及凭据的保护。活动规则的用途在隐私设置中显示，敏感值不进入规则说明。

## 文档导入贡献

`sdk/imports.py` 定义 `DocumentImporter`、`ImportSource`、`ImportProbe`、`ImportContext` 和 `ImportResult`。模板分析和证书上传实际使用 `documents.importers` 集合；外部插件不需要增加主工程路由或修改后缀判断。

清单登记自己的标识，例如：

```json
{"contributes": {"documents.importers": ["community.example/custom"]}}
```

Host 入口通过 `context.contribute("documents.importers", "community.example/custom", importer)` 注册，`importer` 的字段如下。

| 字段 | 要求 |
| --- | --- |
| `version` | 处理器实现的语义版本；行为升级时更新，不等同于协议版本 |
| `api_version` | 默认 `1.0.0`，当前支持第一版协议 |
| `title` | 界面显示名称 |
| `purposes` | `("template",)`、`("certificate",)` 或两者 |
| `extensions` | 小写后缀元组，用于界面说明和文件选择提示，不作为内容验证依据 |
| `probe(source)` | 检查冻结的原件字节，返回 `ImportProbe(format, pages)` 或 `None`；不得调用模型、写文件或修改业务资料 |
| `prepare(source, context)` | 在提供的暂存目录处理本轮副本，返回 `ImportResult`；必须响应取消 |
| `uses_renderer` | 默认 false；需要系统渲染器时设为 true，选中的渲染器及版本随本次处理固定 |

`ImportSource` 含文件名、不可变字节及用途。证书探测必须声明完整页数（1–12），模板 DOCX 无法预先确定分页时可省略页数。模板结果使用 `ImportResult(template=docx_bytes, notices=(...))`；证书结果使用 `ImportResult(pages=(page1_png_bytes, ...), text="本机提取文字")`。结果只接受字节，不能返回任意路径。宿主核验结果类型、大小、DOCX 结构、PNG 头部和像素尺寸，并核对返回页数与探测页数；取消或失败不会发布记录。具体解码质量仍由处理器负责，受信任 Host 插件具备宿主权限，这个契约不能代替操作系统隔离。

模板处理上下文包含本轮独立的隐私 `provider`、设置、冻结资料 JSON、进度回调及可选渲染器。需要模型恢复的处理器必须经过该出口，不得自行发送原件或读取用户凭据。证书导入先在本机生成分页，后续识别只读取已生成页面，再经已有隐私网关处理；不要求 OCR 认识外部插件的私有原件格式。

`GET /api/document-importers?purpose=template|certificate` 返回当前活动目录。`POST /api/templates/analyses` 请求体可带 `importer_id`，证书上传接受同名查询参数。两处原有界面都能选择处理器；只有一个匹配项时允许自动选择，多个匹配项返回 409 并列出候选，不按加载先后接管。扩展名与内容不同仍按实际字节选择。

模板任务、已保存模板及证书附件记录处理器标识、实现版本、插件版本、外部包摘要、配置摘要及原件 SHA-256。重试原始导入会核对这些记录，也会核对需要的渲染器；变更后须保留旧任务并明确重新导入。已经转换完成的模板编辑只操作保存的 DOCX，不重新调用原导入器。历史记录和原件跟随备份，缺包恢复无需执行原插件。

内置贡献为 `sys.docx/import`（可编辑或空白 DOCX）、`ext.import-image/default`、`ext.import-pdf/default`、`ext.import-pdf/scanned-docx`（图片型 DOCX）及 `ext.word/import`（旧版或损坏 Word）。自动分流的兼容函数仅供独立调用；生产流程进入已选处理器的明确格式分支。`import.image`、`import.pdf` 能力暂保留给现有可选依赖，业务导入不再通过它们选择格式。

### 集合贡献的生命周期

Host 清单的 `consumes: ["集合名"]` 声明会执行哪些贡献。宿主按清单自动建立从消费者到所有活动贡献者的排空依赖；它不改变入口注册顺序，也不要求消费时集合非空。`sys.documents` 消费 `documents.importers`，模板和荣誉库依赖 `document.registry`，所以新增、配置变更或停用任意外部导入器都会覆盖它们的请求和任务。旧任务实际结束前不会卸载其提供方，插件作者不必另外猜测所有业务消费者。

## 客户端入口

客户端导出 `activate(context)`。共享入口为 `react`、`react-dom`、`react-dom/client`、`react/jsx-runtime` 和 `@resume-maker/plugin-sdk`；插件构建把它们设为 externals，禁止携带第二份 React。宿主提供 import map 和固定共享资源。

```javascript
import React from "react";

export function activate(context) {
  function Page() {
    const [count, setCount] = React.useState(0);
    return React.createElement("button", {
      onClick: () => setCount(count + 1)
    }, "示例 " + count);
  }
  context.page({
    id: context.id + "/main", title: "示例", order: 100, component: Page
  });
}
```

公开的贡献包括 `page()`、`settingsPage()`、`style()`、`effect()`；内置组件插槽的 props 在 `frontend/src/plugins/slots.ts`，不从组件实现推导。外部插件不能覆盖内置插槽，新增页面不需要修改 App。

客户端服务通过 `provide(name, value, version)` 和 `require(name)` 使用宿主已解析的绑定。激活完成核对实际承诺能力，提供方失败会阻止依赖方激活，卸载撤销登记。`remote(service, method, payload)` 访问清单绑定的唯一远端提供方；`request(method, payload)` 访问自身 RPC 命名空间。

动态资源限定到本机的 `/plugin-assets/<ID>/<摘要>/...`。更新得到新 URL，应用切换前先保护草稿。ESM 模块缓存不承诺立即物理卸载，代码更新使用页面重载。

## Worker 和隔离页面

worker 清单使用 `entrypoints.worker`，声明 execution/sandbox 依赖及 `execution.trusted` 权限。入口通过 stdin 读取一个 JSON 请求，stdout 返回一个 JSON 响应：

```json
{"rpc_version":1,"id":"请求ID","method":"double","payload":21,"generation":7}
```

```json
{"rpc_version":1,"id":"相同请求ID","result":42}
```

`rpc` 为每个方法声明 input_schema、output_schema 及超时。Schema 禁止远端引用；请求、结果和关联 ID 验证通过才发布。每次调用是独立受管进程，参数、解释器及入口摘要受授权绑定。默认 worker 仍具有账户权限；请求 OS 文件/网络强隔离而平台不支持时拒绝执行。

`isolated-client` 使用 opaque origin iframe、CSP 和 MessageChannel。页面监听 `resume-plugin-connect` 取得传入端口；端口消息 `{id, method, payload}`，回复 `{id, ok, result}` 或 `{id, ok:false,error}`。导航及卸载关闭旧端口，迟到结果不返回新会话。主页面令牌不进入 iframe。

## 命令、资料编辑和工作流贡献

`context.contribute(point, id, value, order = 100, version = "1.0.0")` 注册公开客户端贡献。清单 `contributes[point]` 必须列出同一标识，ID 使用 `<插件ID>/<贡献名>`。未声明、重复、未知协议和快捷键冲突会使当前插件激活失败并撤销已注册资源。类型在 `frontend/src/plugins/extensions.ts`，可通过 Client SDK 导入。

| 扩展点 | 值和实际接入 |
| --- | --- |
| `commands` | `{title, shortcut?, run({signal})}`，出现在顶部插件命令菜单；快捷键格式为 `Mod+[Shift+][Alt+]字母或数字` |
| `resume.field_editors` | `{title, component}`，组件接收 `{value, onChange}`，在个人信息页编辑 `document.extensions[插件ID]` |
| `workflow.state_contributors` | `{evaluate(input)}`，接收独立冻结的 `WorkflowInput`，同步返回 `{done, text}` |
| `workflow.steps` | `{title, state, command}`，引用状态和命令贡献 ID，在已启用的制作指引中显示额外步骤 |
| `activity.presenters` | `{sources, present(event)}`，从冻结的已遮盖事件生成纯文本标题及 label/text 行；异常局部显示，完整记录一直可查 |
| `documents.previewers` | `{title, formats, component, availability?}`，按格式注册预览；接收不可变输入字符串和 `DocumentPreviewProps`，可返回暂不可用原因 |

日志展示最多 50 行，每行正文最多 4000 字符。预览组件在边界内挂载，异常不破坏资料或其他预览器。简历使用 `resume/v1` 输入，内置内容和 Word 分页分别注册 `sys.resume/content`、`ext.word/pages`，用户可在“预览方式”中选择。新的资源格式沿用相同注册机制，格式及其输入 schema 由对应流程发布。

系统插件管理命令也通过该接口注册。命令执行前检查窗口冻结，重复触发不并行执行；输入框、组合输入和长按不触发快捷键。卸载发送 AbortSignal 并等待真实执行结束，五秒后未结束则报告清理失败并保留待清理作用域，实际结束后可重试。取消仅约束插件主动响应的任务，不能撤回已发出的外部请求。

窗口收到切换计划后，先保存现有草稿，再冻结整个窗口的新命令、向全部客户端命令发送取消并等待实际收尾，最后再次刷新领域及工作区草稿才确认窗口。当前切换会刷新整页，因此未受影响实例的命令也必须完成收尾；刷新入口再次检查全部命令。五秒未结束或草稿保存失败都不会确认；后续心跳可重试。计划取消后解除命令冻结，原注册仍可使用。

窗口心跳可携带有界的 `title`（300 字符）和 `status`（500 字符），服务器返回本次运行中递增且不复用的 `number`。计划的 `windows_detail` 保留名称、序号、连接状态及最后响应时间。页面通过公开窗口接口 `registerWindowTitle(title, priority)` 注册名称并在卸载时清理，高层扩展页面可覆盖后台工作台标题。管理页显示名称及浏览器标签序号，在线窗口可通过 `locateWindow(id)` 发送同源定位提示；浏览器拒绝聚焦时，目标标签的“待保存”标记供人工辨认。定位只改变标签显示，不确认草稿，也不解除冻结；离线窗口继续要求明确保留恢复副本。

插件管理、提示条的“重新协商并加载”和存储冲突的“载入已保存内容”均通过 `reloadWindow()` 刷新。协调器合并并发刷新请求，先冻结并等待全部命令结束，再保存最终草稿或执行调用方提供的冲突处理及存储准备。超时或保存失败保留当前页面和输入，不执行刷新；命令实际结束后可再次点击重试。

默认刷新在草稿保存失败后读取当前能力；只有确认宿主就绪且插件代次已变化，才改用 `storage.prepareReload()` 核验未保存输入的浏览器恢复副本。所有同阶段草稿回调收尾后才处理失败，避免遗漏迟到输入。副本继续携带旧代次，重新加载后仅供核对，不自动写入当前资料；窗口不会自行提升写入代次。同代次冲突、无法确认宿主状态或副本保存失败仍阻止刷新。

计划的十分钟有效期只限制准备及提交，过期后仍可取消当前任务或退出准备状态；取消校验计划身份及阶段，不重新验证待提交代码。取消其他预览计划不会解除当前计划的冻结。管理页恢复普通启停及包升级的所有活动计划，优先显示正在准备或执行的计划；准备期间刷新的新窗口加入同一确认屏障，旧窗口的恢复副本仍须明确保留。临时注册冲突不会永久停止窗口重试。

每个插件命名空间有一个资料编辑器，可自行组织多项字段。值必须是 JSON，全部扩展资料仍受 1 MB 上限约束。局部写入只更新当前命名空间并保留其他插件资料；迟到编辑和停用后的回调拒绝应用。输入沿用简历的自动草稿及保存组合流程，不自动正式提交。资料变化影响组合保存和历史导出的新旧判断。没有编辑器时保留资料并显示说明，组件错误只替换对应扩展区域。

扩展资料应包含既有降级展示契约：`{display: {title: "栏目名", text: "纯文本"}, ...私有字段}`，或 `{display: {hidden: true}, ...私有字段}`。缺少有效展示契约时导出拒绝，不能静默丢弃内容。编辑器不可改写其他命名空间，也不获得整个简历的可变引用。

工作流状态计算不得产生副作用；异常或无效返回值只使对应步骤显示不可用，不回显异常中的资料正文。步骤命令缺失时禁用操作。贡献按 `order` 及 ID 稳定排序，停用时一起撤销。需要制作指引的插件应声明对 `ext.workflow` 的插件依赖；贡献接口不会自动安装它。

## 包格式及安装

`.rmp` 为 ZIP，根目录含 `manifest.json`、`artifacts.json`、LICENSE 和声明的入口/资源。`artifacts.json` 将每个文件映射到 `{size, sha256}`，包含 manifest，排除自身。安装检查路径、链接、展开大小、完整性、依赖及信任模式；检查阶段不导入代码。

插件管理支持本机包及 HTTPS 下载。检查后确认同一摘要和代码信任，将一个或多个包加入联合候选，统一选择启用状态并检查依赖。候选仅暂存不可变产物，活动索引在试运行成功、旧宿主结束之后才发布。卸载先停用，只移除安装记录并保留资料。旧的单包安装 API 仅用于首次安装为未启用状态，升级必须走候选计划。

下载需要明确的 HTTPS URL 和发布者提供的 SHA-256，不提供自动寻找最新版本的市场。下载目录为 `plugin-downloads/<UUID>/`，实际字节数和未知总长度分别展示，超过 512 MB 拒绝。客户端在请求前生成 UUID；同一来源重复请求幂等，复用身份而改变来源拒绝。取消只有在线程退出后才变为 cancelled，重启把未完成记录标为 interrupted，不自动重发。

| 接口 | 用途 |
| --- | --- |
| `GET/POST /api/plugins/downloads` | 历史记录；以 `{id,url,sha256}` 开始下载 |
| `GET /api/plugins/downloads/{id}` | 查询实际进度及校验后的本地包路径 |
| `POST /api/plugins/downloads/{id}/cancel` | 取消下载并等待真实结束 |
| `PUT /api/plugins/packages/{id}/pin` | `{digest}` 锁定当前精确版本，`null` 明确解锁 |
| `POST /api/plugins/packages/plans` | `{packages,generation,selected?}` 创建联合候选；每项为 `{path,digest,trusted_modes}` |
| `GET /api/plugins/operations` | 查询持久操作，响应丢失后无需重复安装 |
| `POST /api/plugins/plans/{id}/cancel-validation` | 取消正在运行的候选验证 |

计划继续使用 prepare、窗口确认、apply 协议。`validating` 表示正在备份、准备环境、迁移副本或检查健康；`restart-required` 表示等待监督器接管；`booting` 表示正式新宿主仍在健康观察。只有 `committed` 才表示整组成功。失败可能是 failed、cancelled、interrupted、rolled-back 或 recovery-required，页面保留具体结果。

代码更新使用新进程和新的客户端资源 URL，不原地替换 Python 模块。可复现包构造见 `tests/support/plugins.py`，完整流程见 `tests/plugins/test_upgrades.py`。

插件作者可直接复制 [独立笔记示例](../examples/notes-plugin/README.md)，它不依赖内部实现或测试辅助代码。[联合升级请求示例](../examples/notes-plugin/package-plan.json) 会作为真实 HTTP 请求纳入 wheel 验收，避免文档字段和接口模型不同步。`scripts/check_wheel.py` 还在仓库外验收独立构建、官方启动器、安装、多实例 JS 下载、RPC、停用、再次启用和重启恢复。

客户端资源 URL 使用插件定义 ID 和包摘要，多个实例共享同一份不可变代码；页面贡献及 RPC 使用实例 ID。只启用自定义实例也能读取定义资源；最后一个实例停用后，资源和隔离页面入口均返回 404。隔离 iframe 的页面地址同样来自定义资源 URL，其消息桥仍绑定当前实例。

客户端入口既可以是 `client/index.js`，也可以是包根目录的 `index.js`。入口所在目录及其子目录内的已登记公共资源可读取，仍受文件类型、包摘要和逐文件摘要校验约束；Python 源码和 JSON 元数据不会因此公开。

## 依赖环境

可选 `environment_lock` 指向包内 JSON：

```json
{
  "version": 1,
  "wheels": [{
    "name": "example", "version": "1.0.0",
    "file": "wheels/example-1.0.0-py3-none-any.whl",
    "sha256": "完整SHA256"
  }]
}
```

锁须包含完整 wheel 闭包。环境准备使用已安装 uv，创建独立 venv 后执行离线、无索引、固定哈希、只允许二进制 wheel 的安装；再执行 `uv pip check` 和版本检查。正在运行的解释器保持原样。

worker 重启后选择摘要匹配的独立环境。Host 锁须包含 resume-maker 和完整系统依赖。联合 Host 环境合并所有候选 wheel，同名不同版本或不同摘要立即拒绝；完成安装后校验全部所选 Host 依赖。准备中的环境索引不会提前覆盖正式索引。

`resume-maker` 启动器默认运行稳定监督器，实际应用在受管子进程中运行。候选使用备份副本、候选安装目录和环境索引真正启动 Host，执行健康检查后完整关闭。正式切换先停止旧宿主，在维护状态启动新宿主，持续健康观察通过才开放业务。新宿主失败且资料版本兼容时自动恢复原组合；迁移已改写资料版本时保留恢复点并停止自动回退。仅启停或修改配置但声明需要重启的插件也走同一套流程。

直接嵌入 `create_app` 的第三方启动方式不拥有进程监督器，验证通过后可查询 restart-required 并由嵌入方接管重启；官方 CLI 已自动完成。

## 数据迁移和恢复

外部表名为 `plugin_<ID中点和连字符变下划线>_*`，设置前缀为 `<ID>:`，文件位于 `plugin-data/<ID>/`。新表初始化从版本 0 开始，`data.migrations` 指定 JSON 文件：

```json
{
  "version": 1, "from": 0, "to": 1,
  "sql": ["CREATE TABLE plugin_community_example_items(id TEXT PRIMARY KEY)"],
  "settings": [{"key":"community.example:options","value":{}}]
}
```

每步版本递增 1，计划锁定所有摘要和数据库基线。首次仅登记命名空间设置/目录、没有表和迁移文件且目标版本为 1 时，可以直接初始化目录册；后续升级仍须提供完整转换路径。SQL 只访问声明的私有表，不允许附加数据库、PRAGMA、触发器、视图、虚拟表和扩展加载。停机命令：

```sh
resume-maker --data-dir ./data --plugin-data-plan community.example
resume-maker --data-dir ./data --plugin-data-apply ./data/backups/migrations/plan-community.example.json --confirm-digest <计划摘要>
```

维护不激活业务插件。先完整备份，再在副本迁移和校验，失败保留原库。代码回退和资料回退是独立动作；已删除的附件声明仍保留历史所有权。备份不含可执行代码和环境，缺包恢复不会执行其中内容。启动时资料版本不可写或私有表未初始化的可选插件会显示 blocked，依赖它的插件同步阻断；系统插件缺失仍拒绝 ready。配置代次只在实际能力发生变化时推进，重复启动不会反复制造新代次。

## 当前内置能力清单

| ID | 职责 | Host 服务 |
| --- | --- | --- |
| `ext.activity-ui` | 日志界面 |  |
| `ext.ai-conversation` | AI 会话 | conversations, jobs |
| `ext.ai-runtime` | AI 编排 | provider |
| `ext.honor-recognition` | 荣誉识别 |  |
| `ext.honors` | 荣誉库 | honors |
| `ext.import-image` | 图片导入 | import.image |
| `ext.import-pdf` | PDF 导入 | import.pdf |
| `ext.native-shell` | 本机文件交互 |  |
| `ext.ocr` | 本地 OCR | ocr |
| `ext.provider-codex` | Codex 适配器 | model.transport |
| `ext.recruitment` | 招聘收藏 | recruitment |
| `ext.source-code` | 源码资料 | sources |
| `ext.template-adapter` | 模板适配 | templates |
| `ext.template-ai` | AI 模板分析 |  |
| `ext.template-library` | 模板库 | template_library |
| `ext.word` | Word 精确排版 | word.renderer |
| `ext.workflow` | 制作引导 |  |
| `provider.local-assets` | 本地资源后端 | assets.backend |
| `provider.local-credentials` | 本地凭据后端 | credentials.backend |
| `provider.local-sandbox` | 本地材料会话 | sandbox.backend |
| `provider.native-execution` | 平台执行后端 | execution.backend |
| `provider.rapidocr` | RapidOCR | ocr.backend |
| `provider.sqlite` | SQLite 后端 | storage.backend |
| `sys.activity` | 系统日志 | activity |
| `sys.assets` | 资源目录 | assets |
| `sys.backup` | 备份恢复 | backup |
| `sys.credentials` | 凭据借用 | credentials |
| `sys.documents` | 文档流程 | documents, resume_previews, document.registry |
| `sys.docx` | 内置 DOCX 引擎 | docx |
| `sys.drafts` | 持久草稿 | workspace_storage |
| `sys.execution` | 系统执行 | execution |
| `sys.experience` | 经历与版本 | catalog, projects |
| `sys.http` | 本机 HTTP | http |
| `sys.jobs` | 任务协调 | tasks |
| `sys.plugins` | 插件管理 | plugins |
| `sys.privacy` | 隐私保护 | privacy, privacy.store, privacy.gateway |
| `sys.resume` | 简历编排 | resume |
| `sys.sandbox` | 执行策略与材料隔离 | sandbox |
| `sys.settings` | 系统设置 | settings, config |
| `sys.storage` | 系统存储 | db |
| `sys.workbench` | 工作台 | workspace |

## 调度和故障恢复

AI 会话、荣誉识别、模板分析的执行意图与领域输入写入同一事务，再交给 sys.jobs 的执行器。领域状态仍是业务结果的唯一来源，task-execution 记录所有者、处理器版本、提供方和代次。排队任务在重启后标记中断，需要用户明确重试。

同一所有者的等待队列位于线程池外，每个所有者最多派发一个执行头，默认所有未结束任务合计最多 256 项，满时拒绝新任务并保留已提交资料。同类串行语义保持，其他所有者可以使用剩余线程。队列可声明 `on_cancel` 轻量回调，未开始时在池外只做领域收尾，不执行模型主体；未声明的旧调用方继续进入原领域函数处理取消及清理。经历任务终态写入失败时保留最终化屏障，仅重试状态事务，首次立即尝试，随后按 0.5 秒倍增到最多 30 秒间隔；恢复后解除屏障。该补写不自动重发外部调用。

线程池拒绝入队时立即记录失败并释放租约；取消后直到函数和其清理实际结束才允许卸载。终态落盘失败不会伪造在途线程，管理接口返回不含输入正文的诊断，关闭时重试记录。荣誉临时目录和已删除附件完成清理后才释放识别标识，清理失败在停用时重试。

客户端远端集合可以使用 `context.remoteProviders(service)` 读取锁定的提供方列表，再调用 `context.remote(service, method, payload, providerId)`。集合不默认选择第一项；唯一依赖可省略第四个参数。设置页可声明 `openFor`，让既有入口转到该贡献页面；`group: "projects"` 将来源扫描嵌入项目页，`icon` 提供分类图标。已经访问的页面在切换分类时保持挂载。`SettingsPanelProps.registerBeforeClose(guard)` 可注册异步关闭收尾并返回注销函数；收尾失败时设置窗口保留供重试。插件管理借此撤销尚未提交的计划，正在执行的变更仍可在重新打开后恢复。

## 公共存储、引用和资源契约

关系后端可选实现 `sdk.storage.ObservedStore.change_observer()`：上下文管理器返回提交版本读取函数，须覆盖其他连接的已提交变化，并在退出时释放连接。不支持此能力的后端保持完整工作台读取，不能用局部提交计数推断缓存有效。

关系存储通过 `sdk.storage.RelationalStore` 和 `Transaction` 消费。业务服务不导入 SQLite 实现；替换后端必须实现参数化查询、JSON 列、写事务、同事务快照、稳定引用和提交后回调的完整语义，不能只更换连接字符串。`Transaction.after_commit` 用于缓存失效，回滚会丢弃回调。外部插件默认使用 `context.data` 的实例命名空间、CAS 版本及多键事务，任务作用域数据只存在于任务内存。

`prepare_delete(namespace, ids, conn)` 让持久引用规则在业务删除同一事务中核验阻断原因及执行清理。规则归属资料拥有者，停用后仍在数据库内保护历史资料。简历读取模板通过稳定记录引用，项目删除不直接修改 AI 或简历的私有表。公开业务接口位于 `sdk/services.py`，模板资料和分析接口位于 `sdk/templates.py`；导出/预览只接收明确注入的引擎或注册表。

项目配置写入必须提交读取基线：`Projects.save_profile(project_id, profile, expected_profile)`；`Projects.update_sources(project_id, name, sources, expected_name, expected_roots)`。HTTP `PUT /api/projects/{id}/profile` 接收 `{profile, expected_profile}`，`PUT /api/projects/{id}/sources` 接收 `{name, roots, expected_name, expected_roots}`。基线取自读取到的正式项目资料，不能在提交旧表单前替换为最新值；缺少基线返回 422，基线已变化返回 409。用户核对或合并后使用最新基线重新提交，资料库结构仍为 v9。

内置清单 `data.schemas` 和 `data.relations` 声明 SQL 资源，SQLite 按所选模块执行，建表、引用规则和目录册处于同一事务。只执行随发行包安装的内置资源，外部 `data.schemas` 不能绕过命名空间维护权限。外部资料仍使用上面的 JSON 迁移协议。

联合升级计划的 `data_intents` 固定资料版本、包摘要和转换步骤；窗口/任务排空后固定真正的数据库快照。先在 trial 副本执行全部转换，正式停机后再于独立数据库执行整组转换，全部成功且 integrity/FK 校验通过才替换。备份地址和阶段保存在 `plugin-migrations/<计划ID>/operation.json` 及 `host-transition.json`。有资料变化时 `automatic_code_rollback` 为 false；代码回退不恢复数据库。显式恢复命令为：

```sh
resume-maker --data-dir ./data --restore ./backup.zip
```

恢复保留原目录及维护记录，恢复副本不包含可执行插件和解释器；按需重新安装可信包后再启用。新库及恢复库不会为未选择的业务扩展建表。启动及恢复只接受 SQLite v9，旧开发资料在运行当前版本前离线转换并验证。

统一附件接口位于 `sdk/assets.py`。模板、证书、来源证据、成品通过 bundle 暂存和同事务发布；下载租约覆盖完整 HTTP 传输。所有消费者显式注入 assets，持久原件只从资源集合读取。工作目录是可重建的临时副本，成品不再另留第二份持久导出目录。
