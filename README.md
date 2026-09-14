# Resume Maker

[![CI](https://github.com/qch7/resume-maker/actions/workflows/ci.yml/badge.svg)](https://github.com/qch7/resume-maker/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

把项目源码整理成有证据、可编辑、可复用的项目经历，再组合为 Word 简历。

Resume Maker 是运行在本机的项目经历工作台。它通过 Codex CLI 分析受控文本快照，将 AI 建议交给用户确认；经历以不可变版本保存，每份简历明确引用具体版本，避免修改一处影响所有简历。

## 功能

- **项目与来源**：扫描项目集合，支持一个项目关联多个仓库，并记录输入快照、Git 状态和引文证据。
- **经历版本**：逐条或整段编辑、草稿恢复、冲突检查、历史恢复，AI 建议采用后先进入草稿。
- **独立会话**：每条会话独立保存历史、输入和模型会话标识；任务排队，支持取消和超时。
- **简历组合**：选择固定版本及亮点，拖动排序，复用不同模板和组合方案。
- **个人资料与栏目**：在项目经历、个人信息、栏目编排之间切换；填写照片、联系方式、成绩、教育、课程、证书与技能，自定义大栏目和子栏目，调整顺序与显隐。
- **AI 模板适配**：顶部独立“Word 模板”板块分析陌生 DOCX，可视化呈现姓名、联系方式、照片和重复栏目，支持点击原文人工调整、真实试填及模板重开另存。
- **文档导出**：支持内置完整简历、AI 适配模板和手动项目区模板；可下载 Word、追溯清单及可用的 PDF/分页预览。
- **本机工作台**：主题切换、可调布局、制作指引、SQLite 持久化、ZIP 备份与离线恢复。

## 快速开始

需要 Python 3.12+、[uv](https://docs.astral.sh/uv/getting-started/installation/)、Node.js 22.16+ 和已配置的 Codex CLI。**精确页数、PDF 和分页图片需要 Windows + Microsoft Word**；其他平台仍可生成 DOCX。

```powershell
git clone https://github.com/qch7/resume-maker.git
cd resume-maker
.\start.cmd
```

Windows 启动脚本安装锁定依赖、按需构建界面，并打开 <http://127.0.0.1:8765>。关闭运行终端或执行 `stop.cmd` 停止本实例。

也可以在 Windows、Linux 或 macOS 的终端运行：

```sh
uv sync --locked
npm --prefix frontend ci
npm --prefix frontend run build
uv run resume-maker
```

服务仅监听本机回环地址。从源码运行时，个人数据默认保存在项目根目录的 `data/`，数据库文件为 `data/resume.db`，模板、快照、导出与备份也位于该目录；数据目录由 Git 忽略。独立安装包仍默认使用用户目录下的 `.resume-maker`。可用 `RESUME_MAKER_DATA_DIR` 覆盖默认值，或通过命令行优先指定端口和数据目录：

```sh
uv run resume-maker --port 8768 --data-dir /path/to/resume-data --no-browser
```

1. 在设置中导入项目来源，填写本人角色与贡献。
2. 分析项目，在独立会话中讨论并核对证据。
3. 编辑和保存经历，再将指定版本用于当前简历。
4. 填写个人资料并编排栏目，选择亮点；在顶部“Word 模板”中用 AI 识别陌生 Word 并可视化调整，或选择内置版式，保存组合并导出。

Codex 复用当前用户的 CLI 配置，包括自定义 Provider；设置中的实际连接测试用于确认连通性。项目来源仅采集受限制的文本快照，分析内容会交给你配置的 Provider 处理。

## 文档

| 文档 | 内容 |
| --- | --- |
| [使用指南](docs/user-guide.md) | 编辑、独立会话、模板、主题、布局和数据恢复 |
| [开发指南](docs/development.md) | 环境、检查命令、构建包和常见问题 |
| [架构说明](docs/architecture.md) | 目录职责、依赖方向、数据流和扩展位置 |
| [贡献指南](CONTRIBUTING.md) | 修改规范、中文注释、测试和 PR 要求 |
| [安全说明](SECURITY.md) | 本机访问边界、敏感材料和漏洞报告 |
| [更新记录](CHANGELOG.md) | 面向使用者的版本变化 |

## 项目结构

```text
src/resume_maker/
  api/                 # 应用工厂、请求模型、依赖注入、分组路由
  core/                # 实例配置和业务异常
  domain/              # 数据模型和经历字段规则
  services/            # 经历、项目、会话、队列及导出业务
  infrastructure/      # SQLite、初始结构、实例锁和备份恢复
  integrations/        # 源码快照、Provider、OOXML 和 Word 适配
  cli.py               # 本机命令行入口
frontend/src/
  app/                 # 跨业务协调和工作台布局
  features/            # projects / experiences / conversations / resumes / profile / settings / workflow
  shared/              # 通用控件、hooks、网络与存储、数据契约
  styles/              # 按职责组织、保持层叠顺序的样式
tests/                 # 后端业务、HTTP 契约和生命周期回归测试
frontend/tests/        # 纯逻辑和共享草稿注册表测试
scripts/               # 启停、质量检查和构建维护脚本
docs/                  # 使用与开发说明；history/ 保存早期讨论和验收记录
.github/               # CI 和贡献模板
```

## 开发验证

```sh
uv run python scripts/check.py
```

该入口检查 Python 与前端的中文函数说明、模块边界、格式、类型、测试和生产构建。GitHub Actions 在 Windows 和 Ubuntu 上执行相同检查，并验证 wheel 中的前端资源与数据库初始结构。自动测试使用临时目录和 AI 替身。

## 适用范围

完整模板适配支持 DOCX 正文、表格、文本框、页眉页脚和内嵌照片，具体映射需要核对；手动项目区模式仅接受正文段落。图片形式的简历和不支持的 Word 对象需先整理后导入。Word 渲染不可用时，DOCX 仍可下载，页面会显示原因，不估算页数。

本项目采用 [MIT 许可证](LICENSE)。欢迎通过 [Issue](https://github.com/qch7/resume-maker/issues) 反馈问题或按[贡献指南](CONTRIBUTING.md)提交改进。
