# Resume Maker 开发约定

本文件适用于整个仓库。Resume Maker 是单用户本机简历工作台，使用 Python/FastAPI、React/TypeScript 和 SQLite，项目尚未正式发布。

## 开始任务

- 确认仓库目录、当前分支及工作区状态，保留已有改动，只提交本任务文件。
- 阅读 [README](README.md)、[开发规范](docs/conventions.md) 和对应模块；实现见 [架构说明](docs/architecture.md)，操作见 [开发指南](docs/development.md)。
- 工作区存在其他任务的未提交改动时，使用独立 worktree 开发新功能。修改围绕当前任务展开，沿用现有模块和依赖。

## 核心约束

- 单用户服务保留回环监听、Host、Origin 和实例令牌校验。模型材料必须经过隐私网关，只读工具、OCR 和图片保护遵循 [隐私规则](docs/reference/privacy.md)。
- 保存和删除在事务内校验版本。经历修订不可变，简历固定引用版本；草稿冲突、迟到响应和取消后的结果不能覆盖或发布用户输入。
- 插件按声明的能力装配，任务结束后才释放作用域。停用、卸载、失败清理及升级保留资料和依赖，规则见 [插件协议](docs/reference/plugin-sdk.md) 和开发规范。
- 正式资料继续保存在 `data/`，本机沙箱、锁、缓存和构建产物统一放在 `.local/`。安装包的数据和沙箱仍使用既定用户目录；开发验收指定独立临时资料目录。
- 个人资料、密钥、数据库和生成产物不进入 Git。文件清理先核验范围、链接和归属；Word 排版及真实供应商调用按用户授权范围执行。

## Git 提交消息

- 所有新提交和重写后的提交必须遵循 Conventional Commits：`type(scope): description`；无法归属单个模块时可省略 scope，写成 `type: description`。
- type 使用小写，并按实际改动选择：`feat` 新功能、`fix` 缺陷修复、`refactor` 不改变行为的重构、`perf` 性能改进、`docs` 文档、`test` 测试、`build` 构建和依赖、`ci` 持续集成、`chore` 其他维护、`revert` 回退。不能把修复或重构写成新功能。
- scope 使用简短的小写英文模块名，如 `plugins`、`templates`、`drafts`、`startup` 或 `git`，同一模块保持一致。
- 标题使用英文，以小写祈使动词开头，写明具体动作和对象；整行不超过 72 个字符，末尾不加句号。避免 `update`、`fix bugs`、`complete work` 等无法说明具体变化的描述。
- 每个提交围绕一个逻辑改动。需要补充背景时，标题后空一行，在正文说明原因、行为变化、兼容性及实际验证结果；不能声称未执行的检查已经通过。
- 不兼容变更在 type 或 scope 后加 `!`，并在正文后的 footer 中用 `BREAKING CHANGE:` 说明影响和迁移方式。
- 提交前核对暂存 diff 和消息是否一致，并运行 `git diff --cached --check`。重写已有历史须在用户授权范围内先保存备份引用；同步远端只对目标分支使用带明确旧提交值的 `--force-with-lease`。

示例：

```text
feat(plugins): add versioned document importers
fix(plugins): preserve stale window drafts before reload
perf(startup): reuse verified asset migration indexes
docs(git): require conventional commit messages
```

## 分支和 PR

1. 默认从最新 `main` 创建 `codex/<简短功能名>` 分支；用户指定基线或名称时遵循用户要求。
2. 在功能分支开发、检查和提交，通过 PR 交付；默认目标为 `main`，基于未合并功能分支的整理使用该分支作为 PR 目标。
3. PR 说明问题、最终行为、实际验证和必要的数据结构变化。处理审查意见并等待 CI 通过后，再按用户授权合并。
4. 确认 PR 已合并且没有额外提交后，同步目标分支，再删除本次功能分支及失效的远端引用；保留其他 worktree 和未提交内容。

## 验证和交付

代码变更运行完整检查：

```sh
uv run python scripts/check.py
```

涉及打包或资源路径时额外验证：

```sh
uv build --wheel --out-dir .local/artifacts
uv run python scripts/check_wheel.py
```

- 文档改动检查内容、链接和 `git diff --check`；注释改动确认可执行代码未变，并完成格式及质量检查。
- 后端测试按 [测试说明](tests/README.md) 分组，共享构造器放在 `tests/support/`；验证用户能观察到的行为。
- 排版验收查看实际 DOCX 或分页结果。测试替身不能代表真实 Word 或模型验收。
- 交付说明最终改动、验证结果及未执行检查的原因，创建 PR 后附上链接。更多流程见 [贡献指南](.github/CONTRIBUTING.md)。
