# 当前插件开发协议

本文说明当前插件接口、包格式和运行边界。宿主装配及生命周期见 [架构说明](../architecture.md)，开发检查见 [开发指南](../development.md)。

## 本地组合

`plugins/profiles.json` 定义发行策略、minimal 和 standard。18 个系统职责必装，5 个本地提供方补全依赖；标准组合另含 18 个扩展及提供方。系统身份由发行策略判断，第三方不能占用内置 ID。

首次默认使用 standard；`--profile minimal` 或 `--profile standard` 可显式指定启动组合。未指定 profile 时优先读取数据目录 `plugins.json`。已有数据上显式指定 profile 会覆盖保存的选择，日常切换应使用插件管理的排空协议。

顶部插件管理分开显示安装、选择、活动状态及阻断原因，并提供最小/标准组合选择。组合按钮只改变候选选择，不立即切换运行能力。用户先勾选完整候选组合，再查看依赖和受影响范围。准备阶段刷新所有窗口草稿，确认后等待请求及后台执行结束，最后应用并刷新客户端。未满足硬依赖的候选被拒绝，不自动猜测供应商。

## 清单及依赖

Python 公共入口在 `resume_maker.sdk`，定义见 `sdk/manifest.py`、`context.py`、`model.py` 和 `services.py`。清单拒绝未知字段，插件版本和协议版本使用稳定 SemVer；Python 分发依赖使用 PEP 440。

```json
{
  "manifest_version": 1,
  "id": "community.example",
  "title": "示例能力",
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
- 依赖值可以是版本字符串，或 `{version, cardinality, provider}`。集合基数为 `many`，唯一能力为 `one`；多个候选必须明确选择，不能按装载顺序抢占。
- `optional` 是当前 Host 可选依赖；存在时验证版本并加入激活依赖。
- `enhances` 声明插件给其他服务附接的行为，用于计算重建和排空范围。必须同时声明目标依赖。此影响图允许双向关系，不能拿来做激活拓扑排序。
- `plugins` 约束其他插件的版本；`dependencies` 约束 Python 分发依赖。依赖不满足时不能激活。
- `config_schema` 校验配置；当前管理界面提供 JSON 编辑。计划锁定配置和包摘要，变化后旧计划失效。

服务、贡献和实例代次相互独立。`InstanceSpec {id, plugin, bindings}` 为插件定义创建稳定实例，非默认实例要求 `instances.multiple=true`。提供唯一服务的插件仍不能靠多实例绕过服务基数；集合提供方须明确绑定。插件管理支持创建独立实例、分别编辑配置和选择 Host/Client/remote 提供方，停止或移除实例保留资料。

应用作用域可以拥有多个工作区，工作区可以拥有任务作用域。短生命周期实例能消费父服务，父实例不能依赖任务实例。工作区使用独立数据目录；任务权限不得超过提交者的权限。`PluginContext` 提供 `plugin_id`、`instance_id`、`scope_id` 和独立配置。`context.health(check)` 在发布前检查实际能力，失败回收候选并恢复此前配置。

声明 `storage.instances` 后，`context.data` 提供 `get/set/delete/transaction`，每个键使用 `expected_version` 比较版本。应用和工作区资料按作用域及实例隔离，任务资料只驻留本轮内存。停用后旧句柄失效，持久记录保留；删除记录保留版本墓碑，`null` 是业务值。

任务提交可以携带 `plugin_instances` 和 `plugin_configs`；`sys.jobs` 在入队前固定代码摘要、配置、代次和权限，执行期间通过 `sdk.tasks.current_task().require(instance, ServiceKey(...))` 读取本轮实例。任务取消后等待真实处理和作用域清理结束。清理失败的作用域继续阻止相关插件变更。

### 配置覆盖

配置顺序为清单默认值、有序 bundle、工作区覆盖、本次启动覆盖。`ConfigurationEdit` 使用 `replace` 替换整份对象，`set` 按属性路径设置，`reset` 恢复该层开始前的继承值；数组整体替换，重置操作不能携带 `value`。管理计划返回有效配置、逐字段来源和摘要，全部通过 schema 校验后才可应用。

插件管理的 JSON 编辑是工作区整份替换，字段及整份重置使用独立按钮，计划内可查看最终结果。`POST /api/plugins/plans` 还接受 `config_edits`，例如 `{instance: "community.example", operation: "set", path: ["options", "count"], value: 2}`。`reset` 使用相同路径且省略 value；空路径表示重置整份配置。

`--plugin-config <JSON文件>` 接受 `{bundles: [{name, edits}], startup: [操作...]}`。bundle 按顺序应用并持久保留；startup 只在当前启动生效，普通重启不会把临时值当成永久配置。发行组合也可通过 `profiles.json` 的 `profile_bundles` 及 `bundles` 声明默认配置。文件不执行代码，不包含密钥原文，凭据继续使用独立引用。

## Host 服务、路由及资源

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

应用内业务路由通过 `Depends(service("服务名"))` 显式注入；建立快照时核验所有权。领域方法签名定义在 `sdk/services.py` 的 Protocol 中，HTTP 层不再为类型声明导入对应服务实现。已有 HTTP 路径保持兼容，模块内部的端点分组由插件注册确定。

持久资源使用 `assets.stage(owner, bytes, media_type)`，之后在业务数据库事务内 `assets.publish(conn, staged, references)`。未提交的暂存记录不允许读取；读取通过 `lease()` 保持摘要和生命周期。历史模板、荣誉和证据目录仍由各插件的持久描述枚举，不能以插件停用为由清理它们。

业务删除引用时，在同一事务调用 `assets.release_reference(conn, id, owner, reference)`；没有引用和读取租约后才可 `tombstone(id, owner)`。失败暂存、墓碑及无登记的 UUID 资源目录默认保留至少 24 小时，停机通过 `--asset-gc-plan` 生成精确回收计划，再用 `--asset-gc-apply <文件> --confirm-digest <摘要>` 确认。回收持有备份共用的数据库写锁，复核所有记录和文件摘要后才删除。已发布资源不会因关闭插件或长期未访问而回收。

工作台查询使用 `workspace.queries` 贡献，接收已有读取事务和返回字典。修改已有简历来源时保留历史确认快照；不要让关闭扩展导致普通保存删去未知内容。

## 文档引擎贡献

`sdk/documents.py` 定义 `DocumentInput`、`DocumentEngine` 和 `DocumentRenderer`。第一版引擎输出可编辑 DOCX，渲染器补充 PDF 和分页。内置版式、模板填充及 Word 分别贡献 `sys.docx/default`、`ext.template-adapter/default`、`ext.word/default`，不再靠改变全局生成函数选择实现。

引擎清单声明 `contributes.documents.engines`，生成入口用 `context.contribute("documents.engines", "当前插件ID/docx", DocumentEngine("1.0.0", generate))` 注册。渲染器使用 `documents.renderers` 和 `DocumentRenderer`。标识须属于贡献者，重复标识和不兼容版本拒绝使用；模板引擎须声明 `accepts_template=True`。外部引擎声明对 `documents` 的依赖及 `enhances`，进入反向排空范围。

`generate(output_path, frozen_input)` 只能消费冻结输入；`frozen_input.values()` 返回独立的简历、项目及模板对象，`template_bytes` 是同一快照中的原件。生成失败或没有输出时不发布成品。预览和导出共用注册表，清单记录选中引擎、渲染器和版本。默认选择保持官方绑定，其他引擎必须明确指定。

`GET /api/document-engines` 列出活动引擎和渲染器；导出及预览接受可选查询参数 `engine_id`、`renderer_id`。引擎停用后重新生成返回明确错误，历史成品仍可下载。现有简历界面沿用默认引擎；外部页面可通过公开 API 提供自己的选择交互。

## 资料来源和补充隐私规则

`sdk/sources.py` 的 `ResumeSource` 注册到 `resume.sources`。`browse(reader, cursor, query, limit)` 返回 `SourcePage`，每页最多 100 条；`resolve(reader, ids)` 只返回明确请求的 `SourceItem`。提供方只发布已核对资料，查询共用简历保存或读取事务的只读快照，不拥有提交权限。

`GET /api/resume-sources` 列出来源，`GET /api/resume-source-items?provider=<贡献ID>` 支持 cursor、query 和 limit。栏目编辑器的“从资料来源添加”直接消费该接口，选择只进入草稿。条目保存 `source: {provider,id,version}`，内容存入原有文字字段，因此缺包后仍能预览和导出。

来源同步只改变所属文字及自定义字段的值，简历保留显隐、顺序、手工字段和自定标签。未返回的条目保留原快照；停用前系统固化最后确认内容并递增简历版本，旧草稿仍走冲突检查。来源删除应在同一事务调用公开的 `resume.preserve_sources(conn)`。荣誉库使用相同协议，并通过 `legacy_prefix` 兼容旧的 `honor:` 条目；新插件不要声明其他来源已占用的历史前缀。

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

线程池拒绝入队时立即记录失败并释放租约；取消后直到函数和其清理实际结束才允许卸载。终态落盘失败不会伪造在途线程，管理接口返回不含输入正文的诊断，关闭时重试记录。荣誉临时目录和已删除附件完成清理后才释放识别标识，清理失败在停用时重试。

客户端远端集合可以使用 `context.remoteProviders(service)` 读取锁定的提供方列表，再调用 `context.remote(service, method, payload, providerId)`。集合不默认选择第一项；唯一依赖可省略第四个参数。设置页可声明 `openFor`，让既有入口转到该贡献页面，例如来源扫描声明 `["projects"]`。

## 公共存储、引用和资源契约

关系存储通过 `sdk.storage.RelationalStore` 和 `Transaction` 消费。业务服务不导入 SQLite 实现；替换后端必须实现参数化查询、JSON 列、写事务、同事务快照、稳定引用和提交后回调的完整语义，不能只更换连接字符串。`Transaction.after_commit` 用于缓存失效，回滚会丢弃回调。外部插件默认使用 `context.data` 的实例命名空间、CAS 版本及多键事务，任务作用域数据只存在于任务内存。

`prepare_delete(namespace, ids, conn)` 让持久引用规则在业务删除同一事务中核验阻断原因及执行清理。规则归属资料拥有者，停用后仍在数据库内保护历史资料。简历读取模板通过稳定记录引用，项目删除不直接修改 AI 或简历的私有表。公开业务接口位于 `sdk/services.py`，模板资料和分析接口位于 `sdk/templates.py`；导出/预览只接收明确注入的引擎或注册表。

内置清单 `data.schemas` 和 `data.relations` 声明 SQL 资源，SQLite 按所选模块执行，建表、引用规则和目录册处于同一事务。只执行随发行包安装的内置资源，外部 `data.schemas` 不能绕过命名空间维护权限。外部资料仍使用上面的 JSON 迁移协议。

联合升级计划的 `data_intents` 固定资料版本、包摘要和转换步骤；窗口/任务排空后固定真正的数据库快照。先在 trial 副本执行全部转换，正式停机后再于独立数据库执行整组转换，全部成功且 integrity/FK 校验通过才替换。备份地址和阶段保存在 `plugin-migrations/<计划ID>/operation.json` 及 `host-transition.json`。有资料变化时 `automatic_code_rollback` 为 false；代码回退不恢复数据库。显式恢复命令为：

```sh
resume-maker --data-dir ./data --restore ./backup.zip
```

恢复保留原目录及维护记录，恢复副本不包含可执行插件和解释器；按需重新安装可信包后再启用。新库及恢复库不会为未选择的业务扩展建表。SQLite v6/v7 启动先备份再升到 v8，原件迁移日志可在中断后继续。

统一附件接口位于 `sdk/assets.py`。模板、证书、来源证据、成品通过 bundle 暂存和同事务发布；下载租约覆盖完整 HTTP 传输。历史目录只在兼容迁移时读取，发布后核对原件清单和所有摘要才清理旧副本。工作目录是可重建的临时副本，成品不再另留第二份持久导出目录。
