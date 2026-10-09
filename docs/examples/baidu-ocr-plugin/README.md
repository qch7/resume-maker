# 百度云 OCR 独立插件

这是可单独构建和安装的外部插件，不修改 Resume Maker 的宿主、隐私系统或内置插件。源码放在示例目录只是便于版本管理，整个目录可复制到仓库之外开发。

- 插件身份：`community.baidu-ocr`，版本 `1.0.0`。
- 提供能力：`ocr.backend@1.0.0`，通过现有 `ext.ocr` 接入图片、扫描 PDF、证书和模板识别。
- 接口：百度 `accurate` 高精度含位置版，或 `general` 标准含位置版。
- 需要当前插件系统、Python 3.12+、Pillow 11–12 和 PyMuPDF 1.25+。
- 适配和安装验证基于宿主提交 `65f7d6e`；宿主当前仍标记为 SDK 1.0.0，不能据此推断较早版本包含相同功能。

安装和启用本身不请求百度，不读取待识别材料。设置页的鉴权检查只获取令牌；图片识别才调用可能计费的 OCR 接口。

## 构建

构建器只使用 Python 标准库，可在任意目录执行：

```powershell
python build.py D:\Downloads\community.baidu-ocr-1.0.0.rmp
```

生成 `.rmp` 和完整文件的 `.rmp.sha256`。包明确枚举发布文件，不包含凭据、缓存、测试数据或系统代码。ZIP 内的 `artifacts.json` 是逐文件摘要，完整 ZIP 的 SHA-256 用于下载校验，两者不应混用。

## 准备凭据

在百度智能云创建应用，开通需要的**含位置版**接口，取得 API Key 和 Secret Key。`accurate_basic`、`general_basic` 不提供所需的完整位置结果，本插件不使用它们。

用源码目录中的助手交互创建凭据文件：

```powershell
python configure_credentials.py "$env:LOCALAPPDATA\ResumeMaker\credentials\baidu-ocr.json"
```

助手隐藏输入并拒绝覆盖已有文件。也可以自行创建 UTF-8 JSON 文件，其结构为：

```json
{
  "api_key": "你的 API Key",
  "secret_key": "你的 Secret Key"
}
```

配置里只存文件的绝对路径。文件不随插件打包、不随工作区备份，换机后须重新配置。不要把密钥放入普通插件 JSON 配置。文件权限由本机账户管理；助手的 Unix `0600` 不能替代 Windows ACL。

## 安装及替换

1. 打开 **设置 → 插件**，选择本地 `.rmp`，检查包并确认 `trusted-host` 和 `trusted-client` 代码信任，然后安装。
2. 展开“百度云 OCR”的配置，填写 `credentials_file` 的绝对路径，并选择 `accurate` 或 `general`。
3. 在同一份待应用选择中停用 **RapidOCR**、启用 **百度云 OCR**，保留 **本地 OCR**（`ext.ocr`，当前名称来自原宿主）。点击“查看变更”并应用。
4. 打开新增的 **设置 → 百度 OCR** 页面，点击“检查百度鉴权”。鉴权成功不代表识别接口权限和额度已通过；它们在实际识别时校验。
5. 使用原有图片、证书或模板流程试用。切回时在同一份变更中停用百度插件并启用 RapidOCR。

两个引擎都提供唯一 `ocr.backend` 能力，同时启用会被宿主拒绝。插件不会覆盖或自动关闭 RapidOCR，也不会偷偷回退其他供应商。

### 依赖未满足时

清单声明的依赖由宿主检查，当前安装机制不会因为声明就自动从 PyPI 安装。原先能运行 RapidOCR 的环境通常已有 Pillow 和 PyMuPDF。如果缺少它们，关闭宿主，在**宿主实际使用的 Python 环境**安装后重启：

```powershell
uv pip install --python "宿主Python的绝对路径" "pillow>=11,<13" "pymupdf>=1.25,<2"
```

不需要 RapidOCR、PaddlePaddle、百度 Python SDK、Node 或前端构建工具。HTTP 请求使用 Python 标准库；前端直接复用宿主发布的 React。

## 配置

| 字段 | 默认 | 作用 |
| --- | --- | --- |
| `credentials_file` | 空 | 外部凭据 JSON 文件的绝对路径；未配置时允许启用以查看设置 |
| `api` | `accurate` | `accurate` 高精度含位置版或 `general` 标准含位置版 |
| `request_timeout_seconds` | 20 | 每次网络请求等待秒数，范围 1–30 |
| `image_long_side` | 2400 | 上传图像最长边，范围 512–4096 |
| `pdf_scale` | 3 | PDF 栅格化倍率，仍受最长边限制 |
| `min_request_interval_seconds` | 1 | 同实例识别请求间隔，范围 0–60 秒 |
| `native_pdf_text` | true | 可靠 PDF 文字页本机提取；扫描页、混合页、隐藏文字层调用 OCR |

配置修改由宿主排空并创建新实例。令牌只保存在实例内存；修改凭据文件内容后会重新鉴权，无需重新安装插件。多个工作台进程的限流不共享。

## 支持范围

支持单帧图片和未加密的 1–12 页 PDF；单文件最多 20 MB、单图 4000 万像素、累计 10 万文字及 6000 行。每页发送重新编码的 RGB PNG，PNG 的 Base64 和表单编码不得超过接口上限：`accurate` 10 MB，`general` 8 MB。可靠 PDF 文字不产生 OCR 调用；混合页合并原生文字和云端结果并按位置去重。

输出包含 `pages`、`text`、`seconds`、`needs_review`、`notice`；每页包含 `width`、`height`、`blocks`、`method`，每行包含 `text`、比例矩形 `box`、0–1 的 `confidence`。缺失置信度使用 0 并要求复核，缺失位置明确失败。图片按 EXIF 方向校正；请求关闭百度自动方向检测以保持上传画布坐标，其他旋转图片建议先转正。

网络失败和限流不自动重试，避免不确定的计费重复；只有百度明确返回令牌无效或过期时重新鉴权并重试一次。取消在锁等待、页间、限流等待和 HTTP 请求前后检查；已经发送的同步 HTTP 请求需返回或超时后结束，随后丢弃结果。停用会等待实际调用结束。

本次按要求保留宿主原有隐私系统行为。百度插件会上传图片及扫描页，宿主原有“本机 OCR”文字及状态尚未调整；插件页面和结果通知标明云端识别。

## 验证

在装有当前 Resume Maker 和测试依赖的环境中运行：

```powershell
python -m pytest -q tests
python -m ruff check .
python -m ruff format --check .
```

测试使用合成密钥、图片和接口响应。覆盖结果格式、换钥、限流、取消、停止屏障、扫描及原生 PDF、多页限制、可复现打包，以及通过真实宿主 HTTP API 安装、替换、停用、再次启用及重启恢复。测试不调用真实百度、不使用真实证书。

插件开发中遇到的协议缺口及建议见 [DEVELOPMENT-NOTES.md](DEVELOPMENT-NOTES.md)。当前协议见 [宿主插件开发文档](https://github.com/qch7/resume-maker/blob/65f7d6e8a0aab28693a18de6c280b18e00eebe66/docs/reference/plugin-sdk.md)。

## 百度官方接口资料

- [高精度含位置版](https://cloud.baidu.com/doc/OCR/s/tk3h7y2aq)
- [标准含位置版](https://cloud.baidu.com/doc/OCR/s/vk3h7y58v)
- [Access Token 获取](https://ai.baidu.com/ai-doc/REFERENCE/Ck3dwjhhu)

接口规格核对日期：2026-10-09。账户开通情况、计费和额度以百度控制台为准。
