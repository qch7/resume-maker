# Resume Maker

本机项目经历工作台。读取项目源码，通过 Codex 生成带证据的经历建议，逐条编辑和保存，再勾选固定版本组合成可编辑 Word 简历。

## 启动

Windows 下安装 [uv](https://docs.astral.sh/uv/getting-started/installation/)、Node.js 22 和 Codex CLI，然后双击 `start.cmd`。首次运行安装 Python 依赖并构建前端，浏览器打开 <http://127.0.0.1:8765>。当前机器已经完成安装和构建。

关闭启动终端可停止服务；后台运行时双击 `stop.cmd`，会取消正在运行的 Codex 任务并关闭本实例。

```powershell
# 更换端口或数据目录
.\start.cmd -Port 8768 -DataDir D:\ResumeMakerData

# 强制重建界面
.\start.cmd -Rebuild
```

服务只监听 `127.0.0.1`。项目源码不需要放进本仓库。个人数据默认保存在 `%USERPROFILE%\.resume-maker`；也可设置 `RESUME_MAKER_DATA_DIR` 或传入 `--data-dir`。

## 使用流程

1. **导入项目**：设置中扫描项目集合并确认归组。一个项目可以关联多个仓库；目录搬家后可在“项目来源与本人贡献”中重新绑定。
2. **分析项目**：点击“分析项目”。Codex 读取固定的文本快照，生成经历建议和待确认问题。角色、日期、个人贡献及量化成果由本人补充。
3. **独立会话**：左侧按项目排列会话，点击项目名称右侧的“＋”为该项目新建会话并进入；支持直接切换、改名和归档，设置中可恢复归档会话。每条会话有独立历史、输入草稿和 Codex 会话 ID。
4. **编辑经历**：采用 AI 建议会先进入草稿。每条亮点的标题和正文均可人工编辑、单独保存；保存一条生成新的经历版本，其他未发布修改仍保留为草稿。点击经历版本旁的“保存全部修改”可一次保存当前项目的全部草稿。可新增、删除、排序并恢复历史版本。
5. **组合简历**：勾选项目和亮点，调整项目顺序。“用于当前简历”明确更新引用版本。保存经历不会修改其他简历中已经固定的旧版本。
6. **导出 Word**：选模板后导出。右侧显示实际页数、逐页预览，并提供 Word、PDF 和版本清单下载。

“内容预览”只展示选择的项目内容；“上次导出预览”是 Word 实际排版。修改组合后需要重新导出才会更新后者。

右上角可选择**浅色、深色、跟随系统**，浏览器会记住偏好。顶部“制作指引”显示当前项目与简历的准备进度，点击步骤或下一步提示可定位到对应操作；未保存草稿、引用旧版本、空白经历、缺少模板和导出过期都会提示。右侧同时显示已选项目与亮点数量，文档内容预览保持白纸样式。

拖动区域之间带短线的分隔条，可调整项目栏、编辑区和简历区的宽度，以及制作指引、简历设置与预览的高度；窄屏下支持上下调整编辑区。布局自动记忆，双击分隔条复位，右上角“重置布局”恢复默认大小。分隔条也支持方向键微调（Shift 加速）和 Home/End 调到边界。制作指引可收起；预览右上角的“放大预览”可独占工作区，按 Esc 或再次点击恢复。

项目／会话侧栏提供两种排序：**铃铛**按最近修改排列，计入经历草稿、已保存版本与会话更新；**A–Z**首次点击正序，再次点击倒序。项目和项目内的会话同时排序，默认最近修改，浏览器记住选择。

亮点和右侧内容预览中的项目，均可按住上下箭头之间的**三横杠**拖动排序；落点线指示位置，拖到滚动区边缘可继续滚动。松手确认，Esc 或拖出列表取消；也可聚焦手柄后按空格、上下方向键、空格完成排序。亮点排序沿用箭头操作，保存为新的经历版本，点击“用于当前简历”更新引用；项目排序保留原引用与亮点选择，浏览器自动记住当前组合，点击“保存组合”正式保存。

## Codex 与 CCSwitch

复用当前用户的 Codex 配置，支持 CCSwitch 配置的中转 Provider。**不要求 `codex login status` 显示已登录**。设置中的“测试实际连接”会执行真实请求；模型和 Profile 留空时继承 CLI 设置。也可填写 Codex 可执行文件的绝对路径。

每轮采用 `codex exec --sandbox read-only --json --output-schema ...`，续聊使用明确的会话 ID。任务全局排队，同一会话只允许一个未完成任务；支持取消、超时、失败重试、重启后中断标记，以及从已保存历史重建模型上下文。

当前已实现完整 Codex Provider；API Provider 保留统一接口，后续接入自己的 Agent。`Provider.run()` 返回统一的结构化建议，不直接修改经历或简历。

## Word 模板

导入时选择项目经历起点，以及下一个需要保留的栏目作为终点。程序复制模板并标记替换区域，保留原文件以及区域外的个人信息、照片、教育背景、专业技能和其他 Word 包内容。

当前适配**项目经历区域由正文段落组成**的 DOCX，已经验证本地原简历。复杂表格或文本框内部的项目区需要另写适配器；程序会拒绝不支持的区域。原模板的分节、分页会保留，内容变长时允许多页。

精确页数与 PDF/图片预览使用 Windows 上的 Microsoft Word。Word 不可用或渲染失败时仍可下载 DOCX，界面会明确显示原因，不估算页数。LibreOffice 与 Word 对浮动文本框的排版可能不同，当前模板以 Microsoft Word 结果为准。

## 数据和恢复

SQLite 是主数据来源。数据目录包含经历修订、草稿、会话、任务、模板、输入快照和导出记录，均不纳入源代码 Git。

在“Codex 与数据”中下载完整 ZIP 备份。关闭应用后恢复：

```powershell
uv run python -m resume_maker.cli --restore "D:\Backups\resume-maker-backup.zip"

# 恢复到另一个独立目录
uv run python -m resume_maker.cli --data-dir "D:\ResumeMakerData" --restore "D:\Backups\backup.zip"
```

恢复前校验 ZIP 路径、数据库和必要资源，拒绝覆盖正在使用的数据目录；原数据保留在同级 `*-before-restore-*` 目录。恢复后使用保存的聊天历史重建 Codex 上下文，不依赖另一台电脑的 CLI 会话文件。项目源码本身不在备份内，搬迁后应重新绑定路径。

输入快照记录来源绝对路径、完整 Git SHA、分支、工作区状态、文件哈希和实际分析文本；普通目录使用内容指纹。自动排除依赖目录、二进制、常见敏感文件并遮盖明显密钥；单文件上限 512 KB、每轮最多 3000 个文件 / 25 MB，遗漏情况记录在快照中。快照用于追溯分析输入，不是完整源码备份。

## 开发与验证

Python 3.12+ / FastAPI / SQLite，React 19 / TypeScript / Vite。运行和依赖锁定文件分别为 `uv.lock`、`frontend/package-lock.json`。

```powershell
uv sync --locked
npm --prefix frontend ci
npm --prefix frontend run build
npm --prefix frontend test
uv run python -m resume_maker.cli --no-browser

uv run pytest -q
uv run ruff check src tests
uv run ruff format --check src tests
npx --prefix frontend prettier --check "frontend/src/**/*.{ts,tsx,css}"
```

前端由 FastAPI 同源提供，无独立前端服务或账号系统。修改前端后重新构建并刷新页面即可。

- `catalog.py`：经历修订、逐字段草稿、采用冲突、组合固定引用。
- `sources.py`：多来源扫描、输入快照、证据匹配。
- `providers.py` / `jobs.py`：Codex 适配、会话、持久队列和进程生命周期。
- `documents.py` / `word_render.py`：模板区域替换和独立 Word 渲染。
- `storage.py`：单实例保护、备份、离线恢复。
- `frontend/src`：项目会话侧栏、编辑器、组合、模板与设置。

具体验收记录见 `docs/development.md`；早期产品讨论保留在 `docs/product-proposal.md`。
