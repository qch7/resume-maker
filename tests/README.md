# 后端测试

测试按功能归属组织，同一功能中的领域校验、服务操作和 HTTP 往返放在一起。跨功能流程按主要验证目标归档，回归用例追加到对应行为文件。

| 位置 | 验证范围 |
| --- | --- |
| `api/` | 应用契约、鉴权、生命周期、系统日志、招聘收藏和本机文件选择 |
| `projects/` | 项目来源登记、分组、草稿、分支、版本、正文顺序和删除 |
| `resumes/` | 简历资料、默认项、显隐、预览和删除 |
| `honors/` | 证书识别、人工核对、荣誉快照和关联同步 |
| `storage/` | 数据库、ZIP 备份恢复和工作区草稿持久化 |
| `providers/` | 模型配置、CLI 协议事件和后台经历任务 |
| `privacy/` | 身份脱敏、上下文隔离、沙箱、马赛克和扫描页保护 |
| `sources/` | 按需源码访问、引用证据、材料读取和本机定位 |
| `templates/` | 模板分析、缓存、修复、映射、填充、版式和模板库 |
| `word/` | DOCX/PDF/图片恢复、OCR 和渲染适配 |
| `test_config.py`、`test_architecture.py` | 全局运行配置和生产代码依赖边界 |
| `support/` | 多个测试文件共用的合成资料、可控 Provider 和任务等待函数 |
| `fixtures/` | 固定接口契约和跨前后端共用的合成资料 |

## 运行

```sh
# 完整后端测试
uv run pytest -q

# 只验证某个功能，或直接运行单个文件
uv run pytest tests/projects -q
uv run pytest tests/templates/test_mapping.py -q

# 过滤特定行为并查看慢用例
uv run pytest tests/privacy -k identifiers -q
uv run pytest -q --durations=15

# 仓库完整检查：Python、前端测试及构建
uv run python scripts/check.py
```

Windows 默认临时目录权限异常时，可以临时指定新的专用目录：`uv run pytest -q --basetemp=output/pytest-local`。pytest 会清空指定目录，只能使用专门存放本轮测试产物的路径。

## 共享代码和隔离

- `conftest.py` 只提供 pytest 自动发现的夹具，不由测试显式导入。`catalog`、`project`、`populated` 按测试创建独立数据库；`fixtures_dir` 提供固定资料目录。
- 仅一个文件使用的辅助函数留在该文件。多个文件共用时放入 `tests.support`，通过绝对路径导入；辅助模块不导入 `test_*.py` 或 `conftest.py`。
- 根层自动夹具对所有分组继续生效：隔离模型配置、阻止真实模型请求，并替换桌面 Word。不要通过移动目录、跳过夹具或放宽断言解决测试失败。
- 使用 pytest 的 `importlib` 导入模式，允许不同功能下存在 `test_library.py` 等同名文件。根层 `__init__.py` 为共享模块提供包入口并注册断言重写，各功能目录无需再添加包标记。
- 固定资料通过 `fixtures_dir` 读取，仓库脚本通过 `pytestconfig.rootpath` 定位，避免根据测试所在深度推算根目录。
- 合并用例时保留边界场景和参数化组合。只有相同前置条件及断言已被覆盖，或验证对象已移除且当前契约已有覆盖时，才删除用例；测试短小或近期未失败不是删除依据。

## 本次整理

79 个测试文件归并为 69 个，共享辅助代码归入 9 个模块。`test_privacy_regressions.py` 按隐私出口、源码材料和 PDF 恢复拆回对应功能；`test_template_robustness.py` 归入模板通用性和修复；原 `test_template_performance.py` 实际验证缓存及会话行为，改名为 `templates/test_cache.py`。

- 草稿改回原值的单独测试并入 `projects/test_revisions.py` 的参数化用例，补入草稿清理和过期版本拒绝断言，并保留三种字段情形。
- 删除已移除模板导入接口的历史 404 用例。`api/test_app.py` 继续对照固定契约核验当前完整接口集合；模板库可用性、保存和导入流程仍有独立覆盖。
- 保留所有其他行为用例和原有平台跳过条件，重复的空进度回调统一到辅助模块。整理后收集 953 个参数化用例，比原来减少 2 个。

## 参考

参考的是具体组织方式，并根据本项目的功能规模选择目录层次：

- [HTTPX tests](https://github.com/encode/httpx/tree/master/tests)：`client/`、`models/` 按功能分组，`common.py` 存放共享辅助代码。
- [pytest testing](https://github.com/pytest-dev/pytest/tree/main/testing)：`logging/`、`python/` 等功能子目录和根层 `conftest.py` 协作。
- [Flask tests](https://github.com/pallets/flask/tree/main/tests)：按功能命名测试文件，共享夹具和模板、静态资料独立存放。
- [pytest 推荐实践](https://docs.pytest.org/en/stable/explanation/goodpractices.html)：测试置于应用源码之外，并使用 `importlib` 导入模式。
