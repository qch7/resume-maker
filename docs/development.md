# 开发指南

## 环境与启动

Python 3.12+、uv、Node.js 22.16+。`.python-version` 与 `.node-version` 记录仓库默认主版本；Python 和前端依赖分别使用 `uv.lock`、`frontend/package-lock.json`。

```sh
uv sync --locked
npm --prefix frontend ci
npm --prefix frontend run build
uv run resume-maker --no-browser
```

前端由 FastAPI 同源提供，修改后重新运行前端构建并刷新浏览器。没有独立 Vite 开发服务器代理，避免绕过首页实例令牌。调试时建议用 `--data-dir` 指向独立目录。

| 配置 | 含义 |
| --- | --- |
| `--data-dir` / `RESUME_MAKER_DATA_DIR` | 数据目录；命令行优先。源码运行默认使用项目 `data/`，独立安装包使用用户目录 `.resume-maker` |
| `--port` | 本机监听端口，默认 8765 |
| `--no-browser` | 启动时不自动打开浏览器 |
| `--restore ZIP` | 持有同一实例锁，离线恢复备份后退出 |
| `RESUME_MAKER_FRONTEND_DIR` | 覆盖静态资源目录；否则使用安装包内资源或仓库 `frontend/dist` |

应用直接读取环境变量，不自动解析 `.env`。运行令牌及实例标识每次创建，不能作为固定配置提交。

## 质量检查

```sh
uv run python scripts/check.py
```

也可逐项执行：

```sh
uv run python scripts/check_quality.py
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
uv run pytest -q
npm --prefix frontend run check
npm --prefix frontend run build
```

格式化使用 `uv run ruff format src tests scripts` 和 `npm --prefix frontend run format`。前端 `check` 包括中文注释与依赖边界、TypeScript、Prettier 和 Node 测试。

后端测试使用 pytest 临时目录和可控 Provider，不需要真实 CLI 鉴权或 Microsoft Word。文档测试使用 DOCX 内容对比验证区域保留，并替换渲染器；真实 Word 排版和真实 Provider 连通性须在有对应环境的本机另行验收。Windows 和 Ubuntu 的 CI 均执行核心测试与安装包检查。

## 真实模板与供应商对照

用户授权发送模板后，可从 CC Switch 只读加载指定的 Codex 供应商：

```sh
uv run python scripts/evaluate_templates.py --cc-switch-db <cc-switch.db> --data-db <resume.db> --templates <模板目录> --output output/template-evaluation/run-1 --providers <供应商名称> <另一供应商名称>
```

可用 `--resume-id` 指定试填资料；缺省选最近更新的未删除简历。供应商名称必须与 CC Switch 一致。每个组合使用独立的 CLI 配置和会话，密钥仅通过子进程环境传递，不修改当前 Codex 配置、CC Switch 选中项或正式简历。脚本不会复用映射缓存，也不手工修正某个模型的结果。

`--templates` 也接受单个 DOCX/PDF 文件，便于修复后只复测受影响的输入。

输出包括每轮请求及其对应 DOCX 快照、原始模型映射、最终映射、校验报告与真实 Word 渲染。`content_check` 检查可见资料、栏目标题、姓名页码和占位符；`record_count_check` 按输入资料允许的总次数核对记录标题或正文，拦截重复填写，允许用户确实填写的同值记录。它们不能替代逐页视觉检查。`passed` 还要求真实渲染成功、原文件未变；任一组合失败时脚本以非零状态退出。比较时同时记录自动修正轮次和版式结果，不能只以 `ready` 作为成功标准。生成目录包含模板及简历资料，仅保存在本地忽略目录，不提交到仓库。

重复样本中每个非 `highlights` 字段只能绑定一次；多处亮点仍按原顺序分配。该约束共用于分析、缓存读取和导出，不按模型或模板设置例外。修正请求的 `validation.node_context` 提供出错区域内绑定节点的准确原文，让模型修正引文和记录边界；不能通过模糊匹配放宽引文校验。

验证通用性时使用独立构造的输入，不需要读取用户简历数据库：

```sh
uv run python scripts/evaluate_generalization.py --cc-switch-db <cc-switch.db> --output output/template-generalization/run-1 --providers <供应商名称> <另一供应商名称> --workers 3
```

包含中英文段落、整行表格、独立双栏、缺字段模板、原生单栏 PDF 和双栏 PDF；原始样本与试填资料完全不同，姓名、栏目名、项目和照片都重新生成。`--generate-only` 只创建夹具；`--cases english-sidebar-pdf chinese-vector-pdf` 可复测部分类型。PDF 夹具及产物通过本机 Word 渲染。

最终 `report.json` 额外检查旧样例残留、姓名重复与照片字节替换，不能仅使用控制台提前打印的基础内容检查。失败的结构化回复保存为 `response-N-invalid.json`，包括有界字段路径反馈。单元测试另覆盖同一映射的栏目改名、节点碎片化、增减记录、隐藏栏目与侧栏误判反例。所有规则共用于各供应商，不得按供应商名称、模板文件名或样例中的专有名词增加分支；失败结果需留在验收记录中，不能只记录重试成功的结果。

## 构建可安装包

```sh
npm --prefix frontend ci
npm --prefix frontend run build
uv build --wheel
uv run python scripts/check_wheel.py
```

构建钩子把前端产物放进 wheel 的 `resume_maker/web`；SQL 初始结构作为包资源分发。检查脚本在仓库外解包并验证导入、资源和建库。开发安装跳过前端打包；正式 wheel 缺少前端构建时会明确失败。

安装本机构建的 wheel 后，`resume-maker` 可在仓库之外启动，无需重新下载 npm 依赖。示例：

```sh
uv tool install ./dist/resume_maker-0.1.0-py3-none-any.whl
resume-maker --no-browser
```

`uv build --sdist` 生成包含前后端源码的源码包；从源码包构建 wheel 时同样需要先安装 Node 依赖并构建前端。

## 常见问题

- **首页提示尚未构建**：运行前端构建，或检查 `RESUME_MAKER_FRONTEND_DIR` 是否指向正确目录。
- **重构后旧进程仍运行**：停止原服务后重新启动；`start.cmd` 检测到已有实例时会复用实例。
- **409 冲突**：这是草稿/组合版本保护。刷新并使用页面提供的服务器草稿恢复入口，不能删除数据库来绕过冲突。
- **Word 预览失败**：先确认 Windows 上已安装 Word。只有 DOCX 正文导出是跨平台能力。
- **换机器后项目来源不存在**：备份不包含原项目源码，恢复后重新绑定来源目录。

早期方案和历史验收记录保存在 [history/](history/)，其中机器环境和测试数量描述的是当时状态。

## 2026-09-12 架构重构验收

- Windows 本机后端 33 项、前端 18 项测试通过；接口契约、实例隔离、异常关闭和共享草稿等待行为均覆盖。
- 183 个 Python 函数、474 个前端函数/回调通过中文说明和模块边界检查；Ruff、TypeScript、Prettier 及生产构建通过。
- 独立数据目录中的浏览器验证完成单条发布、旧简历固定引用、新建会话、输入草稿切换恢复及消息回复；AI 使用可控替身。
- 实际 Microsoft Word 导出成功，生成 DOCX、1 页 PDF、分页图片和版本清单，模板其他栏目保留。
- 检查桌面和 390px 窄屏布局、重载后的默认侧栏状态，浏览器控制台无错误；正式用户数据未用于写入验收。
- wheel 在仓库外完成导入、静态资源和初始结构检查，源码包构建成功。
