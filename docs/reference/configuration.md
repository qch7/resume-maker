# 启动配置

启动输入统一由 `core/environment.py` 的 `LaunchSettings` 声明和验证。CLI、Windows 启停脚本、监督器使用同一解析入口，配置文件不写入 `os.environ`。

## 字段和覆盖顺序

逐字段优先级为：**显式命令行参数 > 进程环境 > 所选配置文件 > 类型化默认值**。未传参数保持未指定，不用脚本默认值覆盖环境配置。只有最终有效值需要通过类型验证；文件的语法、变量声明和重复项始终校验。

| 环境变量 | CLI | 默认及约束 |
| --- | --- | --- |
| `RESUME_MAKER_PORT` | `--port` | `8765`；整数 `1..65535` |
| `RESUME_MAKER_DATA_DIR` | `--data-dir` | 源码根目录 `data/`；独立安装包使用用户目录 `.resume-maker/` |
| `RESUME_MAKER_FRONTEND_DIR` | `--frontend-dir` | wheel 内静态资源，源码回退到 `frontend/dist/` |
| `RESUME_MAKER_PROFILE` | `--profile` | 留空沿用已保存的选择；允许 `minimal`、`standard` |
| `RESUME_MAKER_PLUGIN_CONFIG` | `--plugin-config` | 无；可指定插件组合及启动覆盖的 JSON 文件 |
| `RESUME_MAKER_OPEN_BROWSER` | `--browser` / `--no-browser` | `true`；环境和文件接受 `true/false`、`1/0`、`yes/no`、`on/off`，大小写无关 |

可选目录、组合及配置路径的空值会清除低优先级覆盖，继续使用产品默认或已保存选择。端口和浏览器开关不接受空值。进程中的应用变量按大小写无关方式匹配；配置文件须使用表中的完整大写名称。未知 `RESUME_MAKER_*` 会拒绝启动，避免错拼后静默使用默认值。

## 配置文件和路径

源码安装只自动读取**该源码项目根目录**的 `.env`，不按当前目录向上搜索。独立 wheel 安装不自动读取当前目录或用户目录中的文件，使用 `--env-file PATH` 显式指定。`--no-env-file` 关闭文件读取，仍接受命令行和进程环境。两个开关互斥。

```sh
cp .env.example .env
uv run resume-maker --print-config
uv run resume-maker --env-file ./config/local.env --port 8768
uv run resume-maker --no-env-file --data-dir ./temporary-data --no-browser
```

Windows 复制文件使用 `Copy-Item .env.example .env`。

- 文件使用 UTF-8，可带 BOM，支持 dotenv 的引号、`export` 前缀、空行和注释。
- 文件只接收六个声明的启动变量；拒绝未知变量、重复定义、缺少赋值、语法错误和 `${...}` 插值。没有供应商凭据加载功能。
- 文件中的相对路径以文件所在目录为基准；环境和命令行中的相对路径以调用时的工作目录为基准。路径支持 `~`，不进行环境变量展开。
- Windows 绝对路径建议使用单引号或正斜线，如 `RESUME_MAKER_DATA_DIR='D:\Resume data'`，避免双引号中的反斜线被 dotenv 转义。
- 显式文件不存在、不可读或编码错误会报告配置错误；源码根目录没有 `.env` 时继续使用默认值。

`--print-config` 输出六个有效字段、所选文件位置和逐字段来源，`frontend_override` 表示是否覆盖安装包默认资源，然后退出；不创建资料目录、不取得实例锁、不启动服务和浏览器。错误只包含字段、来源、行号或错误类别，不回显输入值；诊断输出不包含进程环境、令牌及实例 ID。

旧版本没有 dotenv 加载功能。升级后若源码根目录已有其他用途的 `.env`，应整理为上述六个字段，或通过 `--no-env-file` 保留原有进程环境启动方式。供应商凭据继续放在 CLI 配置和凭据服务中。

`Config(...)` 作为程序式应用工厂输入保持独立：只兼容既有资料和前端目录的环境覆盖，不自动读取 `.env`，也不自动套用启动组合。CLI 先完成全部解析，再构造显式 `Config`。避免模块级全局配置，以便多个合成实例及独立目录共存。

## Windows 启停和监督器

`start.cmd` 支持 `-Port`、`-DataDir`、`-FrontendDir`、`-Profile`、`-PluginConfig`、`-Browser`、`-NoBrowser`、`-EnvFile`、`-NoEnvFile`、`-Rebuild` 和 `-PrintConfig`。`stop.cmd` 支持 `-DataDir`、`-EnvFile`、`-NoEnvFile` 和 `-PrintConfig`。两者安装锁定 Python 依赖后调用同一解析器，路径按调用目录解析；指定文件启动时，停止也使用同一文件或显式资料目录。

```powershell
.\start.cmd -EnvFile .\config\local.env -Port 8768 -NoBrowser
.\stop.cmd -EnvFile .\config\local.env
.\start.cmd -NoEnvFile -DataDir .\temporary-data -PrintConfig
```

启动复用只接受目标目录登记且实例身份匹配的服务。停止使用该目录实际实例记录中的端口并核对进程、随机实例身份和令牌。自定义前端目录须提前构建；源码默认前端继续按需构建。

监督器为子宿主固定资料目录、端口、浏览器行为及显式前端覆盖，并始终传入 `--no-env-file`。启动组合和插件配置只在首次普通启动应用；候选切换及后续重启恢复已保存的插件选择。运行期间编辑 `.env` 要在整个启动器退出后重新启动才能生效。未覆盖前端时，新 wheel 继续使用自身资源。

## 子进程环境和配置归属

`core/process_environment.py` 使用 `EnvironmentPolicy` 和共享系统键声明继承规则，筛选不区分键名大小写：

| 职责 | 继承规则 |
| --- | --- |
| 正式宿主 | 保留任意名称的供应商输入及 `CODEX_HOME`，移除已固定的启动变量和旧的内部凭据传输键 |
| 候选试运行、离线环境安装、只读 Git 查询 | 仅基础系统路径、临时目录和用户目录，不继承模型凭据、Python 注入或应用启动变量 |
| worker | 仅基础系统路径；每轮另行指定沙箱 `TEMP/TMP` |
| Word | 仅本机系统、用户、桌面和临时目录变量 |
| Codex 连接 | 系统变量及代理、证书设置，随后只注入当前连接选定的凭据及受控 `CODEX_HOME` |

供应商 URL、模型、思考强度和鉴权继续归属 CLI 连接设置及凭据服务。`RESUME_MAKER_PROVIDER_KEY` 是内部会话传输键，`RESUME_MAKER_TEST_NATIVE_CLI` 是真实 CLI 边界验收开关；两者不属于公开启动配置，也不能写入 `.env`。验证脚本及单元测试使用独立环境，避开开发者的启动变量和配置文件。

用户设置保存在现有资料存储中；插件运行策略由所属 `config/config_schema` 声明；封闭业务状态使用领域或 SDK 契约。前端 API 保持同源；回环监听、Host/Origin 校验和每次随机生成的 token/instance ID 继续由代码管理。

本次设计参考 [FastAPI 模板的类型化配置](https://github.com/fastapi/full-stack-fastapi-template/blob/e99fbaeba3b55190156ebae525ad9d481d76677e/backend/app/core/config.py)、[Reactive Resume 的根目录加载和环境校验](https://github.com/AmruthPillai/Reactive-Resume/blob/b3d8266c5e8f6d8ed8401baa64ceefd912281e7e/packages/env/src/server.ts) 和 [VS Code 的作用域配置注册](https://github.com/microsoft/vscode/blob/26e0111cea3247abadfdd27f991a15a6a13f1c85/src/vs/platform/configuration/common/configurationRegistry.ts)，按本机多实例和插件持久化边界采用显式解析。
