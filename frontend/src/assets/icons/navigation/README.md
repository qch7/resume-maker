# 导航图标

应用侧栏、设置分类、经历编辑及会话标签使用本目录的 SVG。所有图标采用 `24 × 24` 画布、圆角端点及 `1.7` 描边，颜色由当前文字颜色控制。

| 文件              | 用途           |
| ----------------- | -------------- |
| `resume.svg`      | 应用标识       |
| `projects.svg`    | 项目经历       |
| `profile.svg`     | 个人资料       |
| `honors.svg`      | 荣誉证书       |
| `sections.svg`    | 简历栏目       |
| `templates.svg`   | Word 模板      |
| `resumes.svg`     | 简历方案       |
| `recruitment.svg` | 招聘收藏夹     |
| `activity.svg`    | 系统日志       |
| `settings.svg`    | 设置           |
| `panel-left.svg`  | 展开、收起侧栏 |
| `archive.svg`     | 会话归档       |
| `model.svg`       | 模型设置       |
| `plugins.svg`     | 插件管理       |
| `privacy.svg`     | 隐私保护       |
| `backup.svg`      | 资料备份       |
| `edit.svg`        | 经历编辑       |
| `chat.svg`        | AI 会话        |

宿主使用 `shared/components/NavigationIcon.tsx`。插件通过公开入口 `@resume-maker/plugin-sdk/shared/components/NavigationIcon` 使用同名组件或具名图标，例如 `ProjectsIcon`。组件接收 `size`，默认尺寸为 `20`，并支持 `className`、`style`。

组件静态导入 SVG 资源，通过 CSS 遮罩继承 `currentColor`。资源交给 Vite 处理，插件不复制图标，也不拼接资源地址。图标本身隐藏于辅助技术；使用图标的按钮须提供文字或 `aria-label`。

新增导航图标时，在此保存独立 SVG，再补充组件中的名称映射。文件只包含矢量图形，不添加脚本、外链或内嵌图片。业务内容中的操作图标继续归属原组件。
