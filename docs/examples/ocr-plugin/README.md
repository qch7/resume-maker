# 合成 OCR 提供方

此示例只使用公开 SDK，返回固定合成文字，不读取真实图片、不连接供应商。密码字段用于检查配置入口，无需填写任何真实密钥。

在安装了 Resume Maker 的环境复制本目录并执行：

```sh
plugin-sdk validate ./ocr-plugin
plugin-sdk package ./ocr-plugin ./synthetic-ocr.rmp
plugin-sdk test ./synthetic-ocr.rmp --enable ext.ocr
```

在临时工作台安装包后，“能力提供方 → 文字识别引擎”会同时列出本机 RapidOCR 和此示例。选择示例并查看计划，应看到 RapidOCR 停用、示例启用、`ext.ocr` 受影响；应用前当前引擎保持原样。清单提供两个密码引用字段和两个普通参数，可以验收控件间距及保存后再应用的流程。

真实云端插件应实现相同 `OCRBackend`，按实例身份及声明用途借用密码，使用 `http.client` 的截止和取消能力，并自行遵循供应商接口、额度及隐私要求。完整协议见 [插件 SDK](../../reference/plugin-sdk.md)。
