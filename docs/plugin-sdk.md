# 当前插件开发协议

本文对应 `codex/plugin-architecture` 的实际接口。长期目标保留在 [完整规范](plugin-architecture-proposal.md)，差距及最终验收见 [实施记录](plugin-implementation.md)。

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

服务、贡献和实例代次相互独立。当前产品每数据目录一个 Host，每定义一个活动实例；`application` 和 `workspace` 在这个本地 Host 中都只有一个实例。`multiple: true` 和 `scope: task` 会在导入入口前明确拒绝，不会悄悄按工作区单实例运行。任务通过 sys.jobs 的独立执行租约表示，任意多实例容器仍属于完整目标的未达标项。

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

应用内业务路由通过 `Depends(service("服务名"))` 显式注入；建立快照时核验所有权。领域方法签名定义在 `sdk/services.py` 的 Protocol 中，HTTP 层不再为类型声明导入对应服务实现。已有 HTTP 路径保持兼容，模块内部的端点分组由插件注册确定。

持久资源使用 `assets.stage(owner, bytes, media_type)`，之后在业务数据库事务内 `assets.publish(conn, staged, references)`。未提交的暂存记录不允许读取；读取通过 `lease()` 保持摘要和生命周期。历史模板、荣誉和证据目录仍由各插件的持久描述枚举，不能以插件停用为由清理它们。

业务删除引用时，在同一事务调用 `assets.release_reference(conn, id, owner, reference)`；没有引用和读取租约后才可 `tombstone(id, owner)`。失败暂存、墓碑及无登记的 UUID 资源目录默认保留至少 24 小时，停机通过 `--asset-gc-plan` 生成精确回收计划，再用 `--asset-gc-apply <文件> --confirm-digest <摘要>` 确认。回收持有备份共用的数据库写锁，复核所有记录和文件摘要后才删除。已发布资源不会因关闭插件或长期未访问而回收。

工作台查询使用 `workspace.queries` 贡献，接收已有读取事务和返回字典。修改已有简历来源时保留历史确认快照；不要让关闭扩展导致普通保存删去未知内容。

## 文档引擎贡献

`sdk/documents.py` 定义 `DocumentInput`、`DocumentEngine` 和 `DocumentRenderer`。第一版引擎输出可编辑 DOCX，渲染器补充 PDF 和分页。内置版式、模板填充及 Word 分别贡献 `sys.docx/default`、`ext.template-adapter/default`、`ext.word/default`，不再靠改变全局生成函数选择实现。

引擎清单声明 `contributes.documents.engines`，生成入口用 `context.contribute("documents.engines", "当前插件ID/docx", DocumentEngine("1.0.0", generate))` 注册。渲染器使用 `documents.renderers` 和 `DocumentRenderer`。标识须属于贡献者，重复标识和不兼容版本拒绝使用；模板引擎须声明 `accepts_template=True`。外部引擎声明对 `documents` 的依赖及 `enhances`，进入反向排空范围。

`generate(output_path, frozen_input)` 只能消费冻结输入；`frozen_input.values()` 返回独立的简历、项目及模板对象，`template_bytes` 是同一快照中的原件。生成失败或没有输出时不发布成品。预览和导出共用注册表，清单记录选中引擎、渲染器和版本。默认选择保持官方绑定，其他引擎必须明确指定。

`GET /api/document-engines` 列出活动引擎和渲染器；导出及预览接受可选查询参数 `engine_id`、`renderer_id`。引擎停用后重新生成返回明确错误，历史成品仍可下载。现有简历界面沿用默认引擎；外部页面可通过公开 API 提供自己的选择交互。

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

系统插件管理命令也通过该接口注册。命令执行前检查窗口冻结，重复触发不并行执行；输入框、组合输入和长按不触发快捷键。卸载发送 AbortSignal 并等待真实执行结束，五秒后未结束则报告清理失败并保留待清理作用域，实际结束后可重试。取消仅约束插件主动响应的任务，不能撤回已发出的外部请求。

每个插件命名空间有一个资料编辑器，可自行组织多项字段。值必须是 JSON，全部扩展资料仍受 1 MB 上限约束。局部写入只更新当前命名空间并保留其他插件资料；迟到编辑和停用后的回调拒绝应用。输入沿用简历的自动草稿及保存组合流程，不自动正式提交。资料变化影响组合保存和历史导出的新旧判断。没有编辑器时保留资料并显示说明，组件错误只替换对应扩展区域。

扩展资料应包含既有降级展示契约：`{display: {title: "栏目名", text: "纯文本"}, ...私有字段}`，或 `{display: {hidden: true}, ...私有字段}`。缺少有效展示契约时导出拒绝，不能静默丢弃内容。编辑器不可改写其他命名空间，也不获得整个简历的可变引用。

工作流状态计算不得产生副作用；异常或无效返回值只使对应步骤显示不可用，不回显异常中的资料正文。步骤命令缺失时禁用操作。贡献按 `order` 及 ID 稳定排序，停用时一起撤销。需要制作指引的插件应声明对 `ext.workflow` 的插件依赖；贡献接口不会自动安装它。

## 包格式及安装

`.rmp` 为 ZIP，根目录含 `manifest.json`、`artifacts.json`、LICENSE 和声明的入口/资源。`artifacts.json` 将每个文件映射到 `{size, sha256}`，包含 manifest，排除自身。安装检查路径、链接、展开大小、完整性、依赖及信任模式；检查阶段不导入代码。

用户在插件管理选择完整本机路径，检查后确认同一摘要和代码信任。安装只发布不可变产物；首次启用需要另一份组合计划。升级已知插件会要求 Host 重启，当前进程不原地替换 Python 模块。卸载先停用，只移除安装记录并保留资料。

当前安装来源是本机 `.rmp`，没有在线市场或远端下载器。可复现包构造及完整生命周期测试见 `tests/plugins/test_packages.py`。

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

worker 重启后选择摘要匹配的已准备环境。Host 环境需要包含 resume-maker 和完整依赖，管理接口返回启动参数数组，由用户停止旧服务再启动新环境。候选 Host 环境同时校验当前所选 Host 插件的依赖闭包。当前没有自动 Host supervisor 回切或安装进度/取消页面。

## 数据迁移和恢复

外部表名为 `plugin_<ID中点和连字符变下划线>_*`，设置前缀为 `<ID>:`，文件位于 `plugin-data/<ID>/`。新表初始化从版本 0 开始，`data.migrations` 指定 JSON 文件：

```json
{
  "version": 1, "from": 0, "to": 1,
  "sql": ["CREATE TABLE plugin_community_example_items(id TEXT PRIMARY KEY)"],
  "settings": [{"key":"community.example:options","value":{}}]
}
```

每步版本递增 1，计划锁定所有摘要和数据库基线。SQL 只访问声明的私有表，不允许附加数据库、PRAGMA、触发器、视图、虚拟表和扩展加载。停机命令：

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
