## 问题

说明触发场景、原因及修改后用户看到的行为。

## 具体改动

逐条说明实际修改，遵守 [开发约定](../AGENTS.md) 中的写作规则。

## 验证

按 [开发约定](../AGENTS.md) 选择检查范围。简单文档、注释改动只检查内容、链接、差异格式，跳过测试及 CI。

- [ ] `uv run python scripts/check.py`
- [ ] 涉及构建资源时验证 `uv build --wheel --out-dir .local/artifacts`、`scripts/check_wheel.py`
- [ ] 本次改动涉及的说明、文档、锁文件已同步更新
- [ ] 未包含个人数据、密钥或生成产物

补充实际执行的回归检查；未执行的项目请注明原因。
