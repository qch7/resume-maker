# 全项目配置审查和处理清单

审查日期：2026-10-07。初次审查扫描了 673 个跟踪的生产、配置和构建文件，记录 37 组治理建议；这些是分类候选，不能按字面量数量当作缺陷数量。本轮在现有启动配置 PR 内复核后端、前端、脚本、清单和资源消费链，完成适合运行配置的整治。

启动参数使用 `.env`；36 项插件运行参数使用所属插件的不可变类型声明和 `config_schema`。默认值、完整示例和字段表生成自同一声明。用户偏好保存在已有设置，安全边界及格式标准保持有版本的代码策略。业务枚举和整个 API 的类型生成另行列出，未计入本 PR 的已完成工作。

配置入口见 [启动配置](configuration.md)、[完整插件字段](plugin-settings.md) 和 [可运行示例](../../examples/plugin-config.json)。

开源参考使用固定提交的实际实现：

- [FastAPI Full Stack Template：类型化默认与验证](https://github.com/fastapi/full-stack-fastapi-template/blob/e99fbaeba3b55190156ebae525ad9d481d76677e/backend/app/core/config.py)
- [Reactive Resume：确定的 dotenv 位置和 schema 验证](https://github.com/AmruthPillai/Reactive-Resume/blob/b3d8266c5e8f6d8ed8401baa64ceefd912281e7e/packages/env/src/server.ts)
- [VS Code：插件作用域与配置注册](https://github.com/microsoft/vscode/blob/26e0111cea3247abadfdd27f991a15a6a13f1c85/src/vs/platform/configuration/common/configurationRegistry.ts)

## 本轮补充

初次清单未逐项列出 RapidOCR 的 CPU 线程、检测尺寸、首轮与复核尺寸、引擎门槛及 PDF 栅格尺寸。本轮全部纳入 provider.rapidocr，共 11 项。源码 Git 等待、CLI 探测等待和 PNG 预览倍率也分别进入所属插件。OCR 模型按实例装载；重配置不共享旧模型。

## 逐项结论和消费位置

下列文件是初次候选扫描涉及的消费位置，按职责列出便于后续契约重构；行号会随代码修改移动。已经删除或搬迁的路径不当作当前可修改文件。新增运行策略文件和实际字段以生成目录为准。

### A01 · 统一启动参数和可选 .env 入口

已实现：9 项宿主变量集中解析，CLI、Windows 和监督器固定同一有效值

- [.gitignore](../../.gitignore)
- [docs/development.md](../../docs/development.md)
- [scripts/start.ps1](../../scripts/start.ps1)
- [scripts/stop.ps1](../../scripts/stop.ps1)
- [src/resume_maker/cli.py](../../src/resume_maker/cli.py)
- [src/resume_maker/core/config.py](../../src/resume_maker/core/config.py)

### A02 · OCR 页数、文字和行数预算

已收敛：轻量 document_limits 声明 OCR 页数、字符和行数预算，OCR 和恢复预算共用；不作为放宽保护的配置

- [src/resume_maker/integrations/certificates.py](../../src/resume_maker/integrations/certificates.py)
- [src/resume_maker/integrations/ocr_support.py](../../src/resume_maker/integrations/ocr_support.py)
- [src/resume_maker/plugin_packages/ext_honors/client/HonorLibrary.tsx](../../src/resume_maker/plugin_packages/ext_honors/client/HonorLibrary.tsx)
- [src/resume_maker/plugin_packages/provider_rapidocr/local_ocr.py](../../src/resume_maker/plugin_packages/provider_rapidocr/local_ocr.py)

### A03 · 隐私阈值和马赛克图片预算

已收敛：privacy_policy 统一复核阈值和图片数量，隐私出口继续执行固定保护

- [src/resume_maker/integrations/ocr_support.py](../../src/resume_maker/integrations/ocr_support.py)
- [src/resume_maker/integrations/privacy_gateway.py](../../src/resume_maker/integrations/privacy_gateway.py)
- [src/resume_maker/integrations/privacy_layout.py](../../src/resume_maker/integrations/privacy_layout.py)
- [src/resume_maker/integrations/providers/mosaic.py](../../src/resume_maker/integrations/providers/mosaic.py)
- [src/resume_maker/integrations/providers/page_images.py](../../src/resume_maker/integrations/providers/page_images.py)
- [src/resume_maker/integrations/word/templates/images.py](../../src/resume_maker/integrations/word/templates/images.py)

### A04 · 上传、像素和 DOCX 解包上限

已收敛：上传、源图像素、输出图片字节、马赛克和 DOCX 解包分别命名；界面读取后端上传元数据

- [src/resume_maker/integrations/certificates.py](../../src/resume_maker/integrations/certificates.py)
- [src/resume_maker/integrations/document_importers.py](../../src/resume_maker/integrations/document_importers.py)
- [src/resume_maker/integrations/providers/mosaic.py](../../src/resume_maker/integrations/providers/mosaic.py)
- [src/resume_maker/integrations/word/templates/images.py](../../src/resume_maker/integrations/word/templates/images.py)
- [src/resume_maker/integrations/word/templates/mapping.py](../../src/resume_maker/integrations/word/templates/mapping.py)
- [src/resume_maker/plugin_packages/ext_honors/client/HonorLibrary.tsx](../../src/resume_maker/plugin_packages/ext_honors/client/HonorLibrary.tsx)
- [src/resume_maker/plugin_packages/ext_template_adapter/services/templates/tasks.py](../../src/resume_maker/plugin_packages/ext_template_adapter/services/templates/tasks.py)
- [src/resume_maker/plugin_packages/provider_rapidocr/local_ocr.py](../../src/resume_maker/plugin_packages/provider_rapidocr/local_ocr.py)
- [src/resume_maker/plugin_packages/sys_documents/services/document_imports.py](../../src/resume_maker/plugin_packages/sys_documents/services/document_imports.py)

### A05 · 简历字段标识和栏目种类

固定业务契约；另行建议从领域字段与栏目 schema 生成 TS，不属于运行参数配置

- [frontend/src/shared/resume/bodyOrder.ts](../../frontend/src/shared/resume/bodyOrder.ts)
- [frontend/src/shared/resume/defaults/model.ts](../../frontend/src/shared/resume/defaults/model.ts)
- [frontend/src/shared/resume/progress.ts](../../frontend/src/shared/resume/progress.ts)
- [frontend/src/shared/resume/visibility.ts](../../frontend/src/shared/resume/visibility.ts)
- [frontend/src/shared/types/index.ts](../../frontend/src/shared/types/index.ts)
- [src/resume_maker/domain/models.py](../../src/resume_maker/domain/models.py)
- [src/resume_maker/domain/resume.py](../../src/resume_maker/domain/resume.py)
- [src/resume_maker/domain/resume_defaults.py](../../src/resume_maker/domain/resume_defaults.py)

### A06 · AI 任务状态、种类和建议状态

固定 AI 状态机；另行建议集中状态和终态谓词并生成前端类型，保留持久化字符串

- [frontend/src/shared/types/index.ts](../../frontend/src/shared/types/index.ts)
- [src/resume_maker/infrastructure/schema.sql](../../src/resume_maker/infrastructure/schema.sql)
- [src/resume_maker/plugin_packages/ext_ai_conversation/client/Chat.tsx](../../src/resume_maker/plugin_packages/ext_ai_conversation/client/Chat.tsx)
- [src/resume_maker/plugin_packages/ext_ai_conversation/client/ConversationSettings.tsx](../../src/resume_maker/plugin_packages/ext_ai_conversation/client/ConversationSettings.tsx)
- [src/resume_maker/plugin_packages/ext_ai_conversation/client/JobProgress.tsx](../../src/resume_maker/plugin_packages/ext_ai_conversation/client/JobProgress.tsx)
- [src/resume_maker/plugin_packages/ext_ai_conversation/client/ProposalCard.tsx](../../src/resume_maker/plugin_packages/ext_ai_conversation/client/ProposalCard.tsx)
- [src/resume_maker/plugin_packages/ext_ai_conversation/routes/jobs.py](../../src/resume_maker/plugin_packages/ext_ai_conversation/routes/jobs.py)
- [src/resume_maker/plugin_packages/ext_ai_conversation/services/conversations.py](../../src/resume_maker/plugin_packages/ext_ai_conversation/services/conversations.py)
- [src/resume_maker/plugin_packages/ext_ai_conversation/services/jobs.py](../../src/resume_maker/plugin_packages/ext_ai_conversation/services/jobs.py)

### A07 · 荣誉识别状态

固定荣誉状态机；另行建议独立的识别状态契约，不与 AI 队列混并

- [frontend/src/shared/resume/honors/model.ts](../../frontend/src/shared/resume/honors/model.ts)
- [frontend/src/shared/types/honors.ts](../../frontend/src/shared/types/honors.ts)
- [src/resume_maker/plugin_packages/ext_honors/client/HonorEditor.tsx](../../src/resume_maker/plugin_packages/ext_honors/client/HonorEditor.tsx)
- [src/resume_maker/plugin_packages/ext_honors/client/HonorLibrary.tsx](../../src/resume_maker/plugin_packages/ext_honors/client/HonorLibrary.tsx)
- [src/resume_maker/plugin_packages/ext_honors/services/honors.py](../../src/resume_maker/plugin_packages/ext_honors/services/honors.py)

### A08 · 模板任务状态、阶段和确认状态

固定模板状态机；另行建议集中状态、阶段和审查标签，保留开放事件

- [src/resume_maker/plugin_packages/ext_template_adapter/client/TemplateAdapter.tsx](../../src/resume_maker/plugin_packages/ext_template_adapter/client/TemplateAdapter.tsx)
- [src/resume_maker/plugin_packages/ext_template_adapter/client/TemplateProgress.tsx](../../src/resume_maker/plugin_packages/ext_template_adapter/client/TemplateProgress.tsx)
- [src/resume_maker/plugin_packages/ext_template_adapter/client/types.ts](../../src/resume_maker/plugin_packages/ext_template_adapter/client/types.ts)
- [src/resume_maker/plugin_packages/ext_template_adapter/services/templates/tasks.py](../../src/resume_maker/plugin_packages/ext_template_adapter/services/templates/tasks.py)

### A09 · 宿主任务执行状态

固定任务执行协议；另行建议加强 SDK 类型，区分执行结束和业务发布

- [src/resume_maker/infrastructure/task_supervisor.py](../../src/resume_maker/infrastructure/task_supervisor.py)
- [src/resume_maker/sdk/tasks.py](../../src/resume_maker/sdk/tasks.py)

### A10 · 插件、升级计划、下载和生命周期契约

固定插件协议；另行建议各状态机独立类型化，插件及贡献 ID 继续开放

- [src/resume_maker/host_supervisor.py](../../src/resume_maker/host_supervisor.py)
- [src/resume_maker/plugin_packages/sys_workbench/client/features/plugins/PackageDownloads.tsx](../../src/resume_maker/plugin_packages/sys_workbench/client/features/plugins/PackageDownloads.tsx)
- [src/resume_maker/plugin_packages/sys_workbench/client/features/plugins/PluginManager.tsx](../../src/resume_maker/plugin_packages/sys_workbench/client/features/plugins/PluginManager.tsx)
- [src/resume_maker/plugin_packages/sys_workbench/client/features/plugins/planRecovery.ts](../../src/resume_maker/plugin_packages/sys_workbench/client/features/plugins/planRecovery.ts)
- [src/resume_maker/runtime/downloads.py](../../src/resume_maker/runtime/downloads.py)
- [src/resume_maker/runtime/host.py](../../src/resume_maker/runtime/host.py)
- [src/resume_maker/runtime/manager.py](../../src/resume_maker/runtime/manager.py)
- [src/resume_maker/runtime/state.py](../../src/resume_maker/runtime/state.py)
- [src/resume_maker/runtime/upgrades.py](../../src/resume_maker/runtime/upgrades.py)
- [src/resume_maker/sdk/configuration.py](../../src/resume_maker/sdk/configuration.py)
- [src/resume_maker/sdk/manifest.py](../../src/resume_maker/sdk/manifest.py)

### A11 · 日志类别、默认过滤路径和规则限制

采集类别及过滤规则沿用持久化用户偏好；类别类型及 UI 元数据另行统一

- [frontend/src/plugins/activity.ts](../../frontend/src/plugins/activity.ts)
- [frontend/src/shared/lib/activityPreferences.ts](../../frontend/src/shared/lib/activityPreferences.ts)
- [src/resume_maker/domain/activity.py](../../src/resume_maker/domain/activity.py)
- [src/resume_maker/infrastructure/activity.py](../../src/resume_maker/infrastructure/activity.py)
- [src/resume_maker/plugin_packages/sys_activity/routes/activity.py](../../src/resume_maker/plugin_packages/sys_activity/routes/activity.py)

### A12 · 存储键和偏好冲突策略

浏览器草稿与偏好使用现有存储；键工厂及冲突声明另行重构并保留旧键兼容

- [frontend/src/main.tsx](../../frontend/src/main.tsx)
- [frontend/src/shared/components/ThemeSwitch.tsx](../../frontend/src/shared/components/ThemeSwitch.tsx)
- [frontend/src/shared/hooks/useActivityPreferences.ts](../../frontend/src/shared/hooks/useActivityPreferences.ts)
- [frontend/src/shared/hooks/useDocumentImporters.ts](../../frontend/src/shared/hooks/useDocumentImporters.ts)
- [frontend/src/shared/lib/activityPreferences.ts](../../frontend/src/shared/lib/activityPreferences.ts)
- [frontend/src/shared/lib/persistence.ts](../../frontend/src/shared/lib/persistence.ts)
- [src/resume_maker/plugin_packages/ext_activity_ui/client/Activity.tsx](../../src/resume_maker/plugin_packages/ext_activity_ui/client/Activity.tsx)
- [src/resume_maker/plugin_packages/ext_ai_conversation/client/Chat.tsx](../../src/resume_maker/plugin_packages/ext_ai_conversation/client/Chat.tsx)
- [src/resume_maker/plugin_packages/ext_honors/client/HonorEditor.tsx](../../src/resume_maker/plugin_packages/ext_honors/client/HonorEditor.tsx)
- [src/resume_maker/plugin_packages/ext_honors/services/honors.py](../../src/resume_maker/plugin_packages/ext_honors/services/honors.py)
- [src/resume_maker/plugin_packages/ext_provider_codex/client/ProviderSettings.tsx](../../src/resume_maker/plugin_packages/ext_provider_codex/client/ProviderSettings.tsx)
- [src/resume_maker/plugin_packages/ext_recruitment/client/RecruitmentPage.tsx](../../src/resume_maker/plugin_packages/ext_recruitment/client/RecruitmentPage.tsx)
- [src/resume_maker/plugin_packages/ext_template_adapter/client/TemplateAdapter.tsx](../../src/resume_maker/plugin_packages/ext_template_adapter/client/TemplateAdapter.tsx)
- [src/resume_maker/plugin_packages/ext_template_library/client/library/LibraryDialog.tsx](../../src/resume_maker/plugin_packages/ext_template_library/client/library/LibraryDialog.tsx)
- [src/resume_maker/plugin_packages/sys_drafts/services/workspace_storage.py](../../src/resume_maker/plugin_packages/sys_drafts/services/workspace_storage.py)
- [src/resume_maker/plugin_packages/sys_resume/client/features/experiences/Editor.tsx](../../src/resume_maker/plugin_packages/sys_resume/client/features/experiences/Editor.tsx)
- [src/resume_maker/plugin_packages/sys_resume/client/features/experiences/HighlightEditor.tsx](../../src/resume_maker/plugin_packages/sys_resume/client/features/experiences/HighlightEditor.tsx)
- [src/resume_maker/plugin_packages/sys_resume/client/features/experiences/useField.ts](../../src/resume_maker/plugin_packages/sys_resume/client/features/experiences/useField.ts)
- [src/resume_maker/plugin_packages/sys_resume/client/features/profile/defaults/Dialog.tsx](../../src/resume_maker/plugin_packages/sys_resume/client/features/profile/defaults/Dialog.tsx)
- [src/resume_maker/plugin_packages/sys_resume/client/features/resumes/ResumeWorkspace.tsx](../../src/resume_maker/plugin_packages/sys_resume/client/features/resumes/ResumeWorkspace.tsx)
- [src/resume_maker/plugin_packages/sys_resume/client/features/resumes/useResumeComposition.ts](../../src/resume_maker/plugin_packages/sys_resume/client/features/resumes/useResumeComposition.ts)
- [src/resume_maker/plugin_packages/sys_resume/client/features/resumes/useWorkspaceLayout.ts](../../src/resume_maker/plugin_packages/sys_resume/client/features/resumes/useWorkspaceLayout.ts)
- [src/resume_maker/plugin_packages/sys_resume/client/features/settings/Privacy.tsx](../../src/resume_maker/plugin_packages/sys_resume/client/features/settings/Privacy.tsx)
- [src/resume_maker/plugin_packages/sys_resume/client/features/settings/Settings.tsx](../../src/resume_maker/plugin_packages/sys_resume/client/features/settings/Settings.tsx)

### A13 · API 类型和边界规则重复维护

响应 schema 和前端 DTO 生成属于独立契约整治；本 PR 仅生成运行配置 schema，未宣称完成全 API 生成

- [frontend/src/shared/components/CustomFields.tsx](../../frontend/src/shared/components/CustomFields.tsx)
- [frontend/src/shared/components/HonorEntryFields.tsx](../../frontend/src/shared/components/HonorEntryFields.tsx)
- [frontend/src/shared/components/ResizeHandle.tsx](../../frontend/src/shared/components/ResizeHandle.tsx)
- [frontend/src/shared/types/honors.ts](../../frontend/src/shared/types/honors.ts)
- [frontend/src/shared/types/index.ts](../../frontend/src/shared/types/index.ts)
- [src/resume_maker/api/app.py](../../src/resume_maker/api/app.py)
- [src/resume_maker/api/plugin_dispatch.py](../../src/resume_maker/api/plugin_dispatch.py)
- [src/resume_maker/api/schemas.py](../../src/resume_maker/api/schemas.py)
- [src/resume_maker/domain/activity.py](../../src/resume_maker/domain/activity.py)
- [src/resume_maker/domain/experience.py](../../src/resume_maker/domain/experience.py)
- [src/resume_maker/domain/honors.py](../../src/resume_maker/domain/honors.py)
- [src/resume_maker/domain/image_layout.py](../../src/resume_maker/domain/image_layout.py)
- [src/resume_maker/domain/models.py](../../src/resume_maker/domain/models.py)
- [src/resume_maker/domain/recruitment.py](../../src/resume_maker/domain/recruitment.py)
- [src/resume_maker/domain/resume.py](../../src/resume_maker/domain/resume.py)
- [src/resume_maker/domain/resume_defaults.py](../../src/resume_maker/domain/resume_defaults.py)
- [src/resume_maker/domain/templates.py](../../src/resume_maker/domain/templates.py)
- [src/resume_maker/plugin_packages/ext_activity_ui/client/Activity.tsx](../../src/resume_maker/plugin_packages/ext_activity_ui/client/Activity.tsx)
- [src/resume_maker/plugin_packages/ext_activity_ui/client/ActivityMultiSelect.tsx](../../src/resume_maker/plugin_packages/ext_activity_ui/client/ActivityMultiSelect.tsx)
- [src/resume_maker/plugin_packages/ext_activity_ui/client/ActivityTimeFilter.tsx](../../src/resume_maker/plugin_packages/ext_activity_ui/client/ActivityTimeFilter.tsx)
- [src/resume_maker/plugin_packages/ext_ai_conversation/client/Chat.tsx](../../src/resume_maker/plugin_packages/ext_ai_conversation/client/Chat.tsx)
- [src/resume_maker/plugin_packages/ext_ai_conversation/client/ConversationSettings.tsx](../../src/resume_maker/plugin_packages/ext_ai_conversation/client/ConversationSettings.tsx)
- [src/resume_maker/plugin_packages/ext_honors/client/HonorEditor.tsx](../../src/resume_maker/plugin_packages/ext_honors/client/HonorEditor.tsx)
- [src/resume_maker/plugin_packages/ext_honors/client/HonorLibrary.tsx](../../src/resume_maker/plugin_packages/ext_honors/client/HonorLibrary.tsx)
- [src/resume_maker/plugin_packages/ext_honors/routes/honors.py](../../src/resume_maker/plugin_packages/ext_honors/routes/honors.py)
- [src/resume_maker/plugin_packages/ext_provider_codex/client/CodexModels.tsx](../../src/resume_maker/plugin_packages/ext_provider_codex/client/CodexModels.tsx)
- [src/resume_maker/plugin_packages/ext_provider_codex/client/ProviderSettings.tsx](../../src/resume_maker/plugin_packages/ext_provider_codex/client/ProviderSettings.tsx)
- [src/resume_maker/plugin_packages/ext_recruitment/client/BookmarkCard.tsx](../../src/resume_maker/plugin_packages/ext_recruitment/client/BookmarkCard.tsx)
- [src/resume_maker/plugin_packages/ext_recruitment/client/BookmarkEditor.tsx](../../src/resume_maker/plugin_packages/ext_recruitment/client/BookmarkEditor.tsx)
- [src/resume_maker/plugin_packages/ext_recruitment/client/GroupsEditor.tsx](../../src/resume_maker/plugin_packages/ext_recruitment/client/GroupsEditor.tsx)
- [src/resume_maker/plugin_packages/ext_recruitment/client/ImportDialog.tsx](../../src/resume_maker/plugin_packages/ext_recruitment/client/ImportDialog.tsx)
- [src/resume_maker/plugin_packages/ext_recruitment/client/RecruitmentPage.tsx](../../src/resume_maker/plugin_packages/ext_recruitment/client/RecruitmentPage.tsx)
- [src/resume_maker/plugin_packages/ext_recruitment/client/RecruitmentSettings.tsx](../../src/resume_maker/plugin_packages/ext_recruitment/client/RecruitmentSettings.tsx)
- [src/resume_maker/plugin_packages/ext_recruitment/routes/recruitment.py](../../src/resume_maker/plugin_packages/ext_recruitment/routes/recruitment.py)
- [src/resume_maker/plugin_packages/ext_source_code/client/SourceSettings.tsx](../../src/resume_maker/plugin_packages/ext_source_code/client/SourceSettings.tsx)
- [src/resume_maker/plugin_packages/ext_template_adapter/client/AdvancedMapping.tsx](../../src/resume_maker/plugin_packages/ext_template_adapter/client/AdvancedMapping.tsx)
- [src/resume_maker/plugin_packages/ext_template_adapter/client/BindingEditor.tsx](../../src/resume_maker/plugin_packages/ext_template_adapter/client/BindingEditor.tsx)
- [src/resume_maker/plugin_packages/ext_template_adapter/client/BuiltinTemplate.tsx](../../src/resume_maker/plugin_packages/ext_template_adapter/client/BuiltinTemplate.tsx)
- [src/resume_maker/plugin_packages/ext_template_adapter/client/TemplateAdapter.tsx](../../src/resume_maker/plugin_packages/ext_template_adapter/client/TemplateAdapter.tsx)
- [src/resume_maker/plugin_packages/ext_template_adapter/client/TemplateAdjustments.tsx](../../src/resume_maker/plugin_packages/ext_template_adapter/client/TemplateAdjustments.tsx)
- [src/resume_maker/plugin_packages/ext_template_adapter/client/TemplateCanvas.tsx](../../src/resume_maker/plugin_packages/ext_template_adapter/client/TemplateCanvas.tsx)
- [src/resume_maker/plugin_packages/ext_template_adapter/client/TemplateInspector.tsx](../../src/resume_maker/plugin_packages/ext_template_adapter/client/TemplateInspector.tsx)
- [src/resume_maker/plugin_packages/ext_template_adapter/client/TemplateProgress.tsx](../../src/resume_maker/plugin_packages/ext_template_adapter/client/TemplateProgress.tsx)
- [src/resume_maker/plugin_packages/ext_template_adapter/client/TemplateTrial.tsx](../../src/resume_maker/plugin_packages/ext_template_adapter/client/TemplateTrial.tsx)
- [src/resume_maker/plugin_packages/ext_template_adapter/routes/templates.py](../../src/resume_maker/plugin_packages/ext_template_adapter/routes/templates.py)
- [src/resume_maker/plugin_packages/ext_template_library/client/TemplatePicker.tsx](../../src/resume_maker/plugin_packages/ext_template_library/client/TemplatePicker.tsx)
- [src/resume_maker/plugin_packages/ext_template_library/client/library/DeleteTemplateDialog.tsx](../../src/resume_maker/plugin_packages/ext_template_library/client/library/DeleteTemplateDialog.tsx)
- [src/resume_maker/plugin_packages/ext_template_library/client/library/LibraryDialog.tsx](../../src/resume_maker/plugin_packages/ext_template_library/client/library/LibraryDialog.tsx)
- [src/resume_maker/plugin_packages/ext_template_library/client/library/TemplateEntries.tsx](../../src/resume_maker/plugin_packages/ext_template_library/client/library/TemplateEntries.tsx)
- [src/resume_maker/plugin_packages/ext_template_library/client/library/TemplateName.tsx](../../src/resume_maker/plugin_packages/ext_template_library/client/library/TemplateName.tsx)
- [src/resume_maker/plugin_packages/ext_template_library/client/library/Thumbnail.tsx](../../src/resume_maker/plugin_packages/ext_template_library/client/library/Thumbnail.tsx)
- [src/resume_maker/plugin_packages/ext_word/client/TemplatePreview.tsx](../../src/resume_maker/plugin_packages/ext_word/client/TemplatePreview.tsx)
- [src/resume_maker/plugin_packages/ext_workflow/client/ExtensionSteps.tsx](../../src/resume_maker/plugin_packages/ext_workflow/client/ExtensionSteps.tsx)
- [src/resume_maker/plugin_packages/ext_workflow/client/Workflow.tsx](../../src/resume_maker/plugin_packages/ext_workflow/client/Workflow.tsx)
- [src/resume_maker/plugin_packages/sys_activity/routes/activity.py](../../src/resume_maker/plugin_packages/sys_activity/routes/activity.py)
- [src/resume_maker/plugin_packages/sys_drafts/routes/workspace_storage.py](../../src/resume_maker/plugin_packages/sys_drafts/routes/workspace_storage.py)
- [src/resume_maker/plugin_packages/sys_plugins/routes/plugins.py](../../src/resume_maker/plugin_packages/sys_plugins/routes/plugins.py)
- [src/resume_maker/plugin_packages/sys_privacy/routes/privacy.py](../../src/resume_maker/plugin_packages/sys_privacy/routes/privacy.py)
- [src/resume_maker/plugin_packages/sys_resume/client/features/experiences/DiscardChangesDialog.tsx](../../src/resume_maker/plugin_packages/sys_resume/client/features/experiences/DiscardChangesDialog.tsx)
- [src/resume_maker/plugin_packages/sys_resume/client/features/experiences/Editor.tsx](../../src/resume_maker/plugin_packages/sys_resume/client/features/experiences/Editor.tsx)
- [src/resume_maker/plugin_packages/sys_resume/client/features/experiences/EvidenceDialog.tsx](../../src/resume_maker/plugin_packages/sys_resume/client/features/experiences/EvidenceDialog.tsx)
- [src/resume_maker/plugin_packages/sys_resume/client/features/experiences/HighlightEditor.tsx](../../src/resume_maker/plugin_packages/sys_resume/client/features/experiences/HighlightEditor.tsx)
- [src/resume_maker/plugin_packages/sys_resume/client/features/experiences/HistoryDialog.tsx](../../src/resume_maker/plugin_packages/sys_resume/client/features/experiences/HistoryDialog.tsx)
- [src/resume_maker/plugin_packages/sys_resume/client/features/experiences/MetaEditor.tsx](../../src/resume_maker/plugin_packages/sys_resume/client/features/experiences/MetaEditor.tsx)
- [src/resume_maker/plugin_packages/sys_resume/client/features/experiences/VersionControl.tsx](../../src/resume_maker/plugin_packages/sys_resume/client/features/experiences/VersionControl.tsx)
- [src/resume_maker/plugin_packages/sys_resume/client/features/profile/EntryOrder.tsx](../../src/resume_maker/plugin_packages/sys_resume/client/features/profile/EntryOrder.tsx)
- [src/resume_maker/plugin_packages/sys_resume/client/features/profile/ExtensionFields.tsx](../../src/resume_maker/plugin_packages/sys_resume/client/features/profile/ExtensionFields.tsx)
- [src/resume_maker/plugin_packages/sys_resume/client/features/profile/ProfileEditor.tsx](../../src/resume_maker/plugin_packages/sys_resume/client/features/profile/ProfileEditor.tsx)
- [src/resume_maker/plugin_packages/sys_resume/client/features/profile/SectionEditor.tsx](../../src/resume_maker/plugin_packages/sys_resume/client/features/profile/SectionEditor.tsx)
- [src/resume_maker/plugin_packages/sys_resume/client/features/profile/SectionOrganizer.tsx](../../src/resume_maker/plugin_packages/sys_resume/client/features/profile/SectionOrganizer.tsx)
- [src/resume_maker/plugin_packages/sys_resume/client/features/profile/SourcePicker.tsx](../../src/resume_maker/plugin_packages/sys_resume/client/features/profile/SourcePicker.tsx)
- [src/resume_maker/plugin_packages/sys_resume/client/features/profile/defaults/Dialog.tsx](../../src/resume_maker/plugin_packages/sys_resume/client/features/profile/defaults/Dialog.tsx)
- [src/resume_maker/plugin_packages/sys_resume/client/features/projects/DeleteProjectDialog.tsx](../../src/resume_maker/plugin_packages/sys_resume/client/features/projects/DeleteProjectDialog.tsx)
- [src/resume_maker/plugin_packages/sys_resume/client/features/projects/ProjectSidebar.tsx](../../src/resume_maker/plugin_packages/sys_resume/client/features/projects/ProjectSidebar.tsx)
- [src/resume_maker/plugin_packages/sys_resume/client/features/resumes/Composer.tsx](../../src/resume_maker/plugin_packages/sys_resume/client/features/resumes/Composer.tsx)
- [src/resume_maker/plugin_packages/sys_resume/client/features/resumes/ContentPreview.tsx](../../src/resume_maker/plugin_packages/sys_resume/client/features/resumes/ContentPreview.tsx)
- [src/resume_maker/plugin_packages/sys_resume/client/features/resumes/ExportHistory.tsx](../../src/resume_maker/plugin_packages/sys_resume/client/features/resumes/ExportHistory.tsx)
- [src/resume_maker/plugin_packages/sys_resume/client/features/resumes/ProjectOrder.tsx](../../src/resume_maker/plugin_packages/sys_resume/client/features/resumes/ProjectOrder.tsx)
- [src/resume_maker/plugin_packages/sys_resume/client/features/resumes/ResumeLibrary.tsx](../../src/resume_maker/plugin_packages/sys_resume/client/features/resumes/ResumeLibrary.tsx)
- [src/resume_maker/plugin_packages/sys_resume/client/features/resumes/ResumeSettings.tsx](../../src/resume_maker/plugin_packages/sys_resume/client/features/resumes/ResumeSettings.tsx)
- [src/resume_maker/plugin_packages/sys_resume/client/features/resumes/ResumeWorkspace.tsx](../../src/resume_maker/plugin_packages/sys_resume/client/features/resumes/ResumeWorkspace.tsx)
- [src/resume_maker/plugin_packages/sys_resume/client/features/settings/ActivitySettings.tsx](../../src/resume_maker/plugin_packages/sys_resume/client/features/settings/ActivitySettings.tsx)
- [src/resume_maker/plugin_packages/sys_resume/client/features/settings/Privacy.tsx](../../src/resume_maker/plugin_packages/sys_resume/client/features/settings/Privacy.tsx)
- [src/resume_maker/plugin_packages/sys_resume/client/features/settings/Settings.tsx](../../src/resume_maker/plugin_packages/sys_resume/client/features/settings/Settings.tsx)
- [src/resume_maker/plugin_packages/sys_resume/routes/resumes.py](../../src/resume_maker/plugin_packages/sys_resume/routes/resumes.py)
- [src/resume_maker/plugin_packages/sys_workbench/client/App.tsx](../../src/resume_maker/plugin_packages/sys_workbench/client/App.tsx)
- [src/resume_maker/plugin_packages/sys_workbench/client/features/plugins/PackageDownloads.tsx](../../src/resume_maker/plugin_packages/sys_workbench/client/features/plugins/PackageDownloads.tsx)
- [src/resume_maker/plugin_packages/sys_workbench/client/features/plugins/PluginManager.tsx](../../src/resume_maker/plugin_packages/sys_workbench/client/features/plugins/PluginManager.tsx)
- [src/resume_maker/sdk/configuration.py](../../src/resume_maker/sdk/configuration.py)
- [src/resume_maker/sdk/imports.py](../../src/resume_maker/sdk/imports.py)
- [src/resume_maker/sdk/manifest.py](../../src/resume_maker/sdk/manifest.py)
- [src/resume_maker/sdk/privacy.py](../../src/resume_maker/sdk/privacy.py)
- [src/resume_maker/sdk/services.py](../../src/resume_maker/sdk/services.py)
- [src/resume_maker/sdk/sources.py](../../src/resume_maker/sdk/sources.py)

### A14 · 缓存版本与文档同步

已收敛：缓存版本按来源命名，文档修正为当前 PDF 契约；属于随代码发布的契约

- [docs/architecture.md](../../docs/architecture.md)
- [src/resume_maker/integrations/word/image/header.py](../../src/resume_maker/integrations/word/image/header.py)
- [src/resume_maker/integrations/word/image/layout.py](../../src/resume_maker/integrations/word/image/layout.py)
- [src/resume_maker/integrations/word/pdf/geometry.py](../../src/resume_maker/integrations/word/pdf/geometry.py)
- [src/resume_maker/integrations/word/pdf/header_layout.py](../../src/resume_maker/integrations/word/pdf/header_layout.py)
- [src/resume_maker/plugin_packages/ext_template_ai/services/templates/analysis.py](../../src/resume_maker/plugin_packages/ext_template_ai/services/templates/analysis.py)
- [src/resume_maker/plugin_packages/ext_template_ai/services/templates/cache.py](../../src/resume_maker/plugin_packages/ext_template_ai/services/templates/cache.py)

### B01 · AI 功能清单和思考强度提示

功能键属于领域契约，思考强度建议列表归提供方；自定义标识继续开放

- [frontend/src/shared/types/index.ts](../../frontend/src/shared/types/index.ts)
- [src/resume_maker/domain/models.py](../../src/resume_maker/domain/models.py)
- [src/resume_maker/plugin_packages/ext_provider_codex/client/CodexModels.tsx](../../src/resume_maker/plugin_packages/ext_provider_codex/client/CodexModels.tsx)

### B02 · 模型连接默认值

已沿用：模型连接、名称、强度及请求超时保存在现有设置；前端先加载真实设置，移除独立假默认值

- [src/resume_maker/domain/models.py](../../src/resume_maker/domain/models.py)
- [src/resume_maker/plugin_packages/ext_provider_codex/client/ProviderSettings.tsx](../../src/resume_maker/plugin_packages/ext_provider_codex/client/ProviderSettings.tsx)
- [src/resume_maker/plugin_packages/ext_provider_codex/integrations/providers/connection.py](../../src/resume_maker/plugin_packages/ext_provider_codex/integrations/providers/connection.py)

### B03 · 宿主启动、健康观察和关闭等待

已实现：启动就绪、候选观察和健康间隔进入宿主配置；正常服务使用明确的无限期执行

- [scripts/start.ps1](../../scripts/start.ps1)
- [scripts/stop.ps1](../../scripts/stop.ps1)
- [src/resume_maker/cli.py](../../src/resume_maker/cli.py)
- [src/resume_maker/host_supervisor.py](../../src/resume_maker/host_supervisor.py)

### B04 · 任务并发、排队和排空策略

已实现：sys.jobs 的线程数和停止等待；AI、荣誉及模板各自声明停止及排队策略

- [src/resume_maker/infrastructure/task_supervisor.py](../../src/resume_maker/infrastructure/task_supervisor.py)
- [src/resume_maker/plugin_packages/ext_ai_conversation/services/jobs.py](../../src/resume_maker/plugin_packages/ext_ai_conversation/services/jobs.py)
- [src/resume_maker/plugin_packages/ext_honors/services/honors.py](../../src/resume_maker/plugin_packages/ext_honors/services/honors.py)
- [src/resume_maker/plugin_packages/ext_template_adapter/services/templates/tasks.py](../../src/resume_maker/plugin_packages/ext_template_adapter/services/templates/tasks.py)
- [src/resume_maker/plugin_packages/sys_jobs/entry.py](../../src/resume_maker/plugin_packages/sys_jobs/entry.py)
- [src/resume_maker/sdk/manifest.py](../../src/resume_maker/sdk/manifest.py)

### B05 · SQLite 等待和日志连接策略

已实现：provider.sqlite 和 sys.activity 分别声明各自锁等待，保持业务与日志库的不同用途

- [src/resume_maker/infrastructure/activity.py](../../src/resume_maker/infrastructure/activity.py)
- [src/resume_maker/infrastructure/database.py](../../src/resume_maker/infrastructure/database.py)
- [src/resume_maker/plugin_packages/provider_sqlite/entry.py](../../src/resume_maker/plugin_packages/provider_sqlite/entry.py)

### B06 · 日志保留与详情截断策略

已实现：日志天数、条数及锁等待进入 sys.activity；截断深度、字符及集合预算使用固定常量

- [src/resume_maker/api/activity.py](../../src/resume_maker/api/activity.py)
- [src/resume_maker/infrastructure/activity.py](../../src/resume_maker/infrastructure/activity.py)
- [src/resume_maker/plugin_packages/ext_activity_ui/client/model.ts](../../src/resume_maker/plugin_packages/ext_activity_ui/client/model.ts)
- [src/resume_maker/plugin_packages/sys_activity/entry.py](../../src/resume_maker/plugin_packages/sys_activity/entry.py)

### B07 · Word 执行与关闭超时

已实现：ext.word 的执行和关闭超时、PNG 预览倍率；COM 身份与进程回收仍固定

- [src/resume_maker/plugin_packages/ext_word/entry.py](../../src/resume_maker/plugin_packages/ext_word/entry.py)
- [src/resume_maker/plugin_packages/ext_word/integrations/word/controlled.py](../../src/resume_maker/plugin_packages/ext_word/integrations/word/controlled.py)
- [src/resume_maker/plugin_packages/ext_word/integrations/word/rendering.py](../../src/resume_maker/plugin_packages/ext_word/integrations/word/rendering.py)

### B08 · 下载、安装、候选检查和计划有效期

已实现：sys.plugins 声明下载、关闭、安装、候选和计划等待；包大小和浏览器租约保持固定边界

- [src/resume_maker/runtime/downloads.py](../../src/resume_maker/runtime/downloads.py)
- [src/resume_maker/runtime/environments.py](../../src/resume_maker/runtime/environments.py)
- [src/resume_maker/runtime/manager.py](../../src/resume_maker/runtime/manager.py)
- [src/resume_maker/runtime/packages.py](../../src/resume_maker/runtime/packages.py)
- [src/resume_maker/runtime/upgrades.py](../../src/resume_maker/runtime/upgrades.py)

### B09 · 模板回收站、后台清理和AI修正轮次

已实现：回收站保留期、清理间隔和分析轮数归各模板插件；界面使用有效保留期

- [src/resume_maker/plugin_packages/ext_template_ai/services/templates/analysis.py](../../src/resume_maker/plugin_packages/ext_template_ai/services/templates/analysis.py)
- [src/resume_maker/plugin_packages/ext_template_library/services/templates/library.py](../../src/resume_maker/plugin_packages/ext_template_library/services/templates/library.py)

### B10 · 导入格式、扩展名和导入用途

已收敛基础图片扩展名和格式；具体用途及格式仍按现有 SDK 和贡献注册表发布

- [frontend/src/shared/hooks/useDocumentImporters.ts](../../frontend/src/shared/hooks/useDocumentImporters.ts)
- [src/resume_maker/integrations/certificates.py](../../src/resume_maker/integrations/certificates.py)
- [src/resume_maker/integrations/document_importers.py](../../src/resume_maker/integrations/document_importers.py)
- [src/resume_maker/sdk/imports.py](../../src/resume_maker/sdk/imports.py)

### B11 · 荣誉类别、字段和默认标签

荣誉类别、字段和标签属于领域目录，继续保存现有值；另行建议生成类型与 UI 元数据

- [frontend/src/shared/resume/defaults/model.ts](../../frontend/src/shared/resume/defaults/model.ts)
- [frontend/src/shared/resume/honors/entry.ts](../../frontend/src/shared/resume/honors/entry.ts)
- [frontend/src/shared/resume/honors/fields.ts](../../frontend/src/shared/resume/honors/fields.ts)
- [frontend/src/shared/types/honors.ts](../../frontend/src/shared/types/honors.ts)
- [src/resume_maker/domain/honor_entries.py](../../src/resume_maker/domain/honor_entries.py)
- [src/resume_maker/domain/honors.py](../../src/resume_maker/domain/honors.py)
- [src/resume_maker/domain/resume_defaults.py](../../src/resume_maker/domain/resume_defaults.py)

### B12 · 字段标签、默认栏目和正文顺序

栏目和字段展示继续使用持久化布局；共享字段目录及正文顺序另行整理

- [frontend/src/shared/resume/bodyOrder.ts](../../frontend/src/shared/resume/bodyOrder.ts)
- [frontend/src/shared/resume/defaults/model.ts](../../frontend/src/shared/resume/defaults/model.ts)
- [frontend/src/shared/resume/progress.ts](../../frontend/src/shared/resume/progress.ts)
- [frontend/src/shared/resume/visibility.ts](../../frontend/src/shared/resume/visibility.ts)
- [src/resume_maker/domain/experience.py](../../src/resume_maker/domain/experience.py)
- [src/resume_maker/domain/project_layout.py](../../src/resume_maker/domain/project_layout.py)
- [src/resume_maker/integrations/word/full_resume.py](../../src/resume_maker/integrations/word/full_resume.py)
- [src/resume_maker/integrations/word/templates/entry_layout.py](../../src/resume_maker/integrations/word/templates/entry_layout.py)
- [src/resume_maker/integrations/word/templates/project_order.py](../../src/resume_maker/integrations/word/templates/project_order.py)
- [src/resume_maker/integrations/word/templates/review.py](../../src/resume_maker/integrations/word/templates/review.py)
- [src/resume_maker/integrations/word/templates/supplement.py](../../src/resume_maker/integrations/word/templates/supplement.py)
- [src/resume_maker/integrations/word/templates/values.py](../../src/resume_maker/integrations/word/templates/values.py)

### B13 · 招聘收藏协议、导入策略和排序类型

招聘导入、排序及协议属于所属功能契约；不进入部署变量，另行统一类型

- [docs/reference/recruitment-bookmarks.schema.json](../../docs/reference/recruitment-bookmarks.schema.json)
- [src/resume_maker/domain/recruitment.py](../../src/resume_maker/domain/recruitment.py)
- [src/resume_maker/plugin_packages/ext_recruitment/client/ImportDialog.tsx](../../src/resume_maker/plugin_packages/ext_recruitment/client/ImportDialog.tsx)
- [src/resume_maker/plugin_packages/ext_recruitment/client/model.ts](../../src/resume_maker/plugin_packages/ext_recruitment/client/model.ts)
- [src/resume_maker/plugin_packages/ext_recruitment/routes/recruitment.py](../../src/resume_maker/plugin_packages/ext_recruitment/routes/recruitment.py)
- [src/resume_maker/plugin_packages/sys_resume/client/features/projects/sort.ts](../../src/resume_maker/plugin_packages/sys_resume/client/features/projects/sort.ts)

### B14 · 前端轮询、重连与心跳

已命名：宿主心跳与重连、日志、荣誉、模板、下载、计划和预览分别持有轮询默认；不增加构建环境开关

- [frontend/src/main.tsx](../../frontend/src/main.tsx)
- [frontend/src/plugins/window.ts](../../frontend/src/plugins/window.ts)
- [src/resume_maker/plugin_packages/ext_activity_ui/client/useActivity.ts](../../src/resume_maker/plugin_packages/ext_activity_ui/client/useActivity.ts)
- [src/resume_maker/plugin_packages/ext_honors/client/HonorLibrary.tsx](../../src/resume_maker/plugin_packages/ext_honors/client/HonorLibrary.tsx)
- [src/resume_maker/plugin_packages/ext_template_adapter/client/TemplateAdapter.tsx](../../src/resume_maker/plugin_packages/ext_template_adapter/client/TemplateAdapter.tsx)
- [src/resume_maker/plugin_packages/sys_resume/client/features/resumes/ResumeWorkspace.tsx](../../src/resume_maker/plugin_packages/sys_resume/client/features/resumes/ResumeWorkspace.tsx)
- [src/resume_maker/plugin_packages/sys_workbench/client/features/plugins/PackageDownloads.tsx](../../src/resume_maker/plugin_packages/sys_workbench/client/features/plugins/PackageDownloads.tsx)
- [src/resume_maker/plugin_packages/sys_workbench/client/features/plugins/PluginManager.tsx](../../src/resume_maker/plugin_packages/sys_workbench/client/features/plugins/PluginManager.tsx)

### B15 · 草稿防抖、预览防抖与客户端排空

已命名：共享保存防抖和客户端停止默认；Word 预览使用局部默认及现有函数参数覆盖

- [frontend/src/plugins/extensions.ts](../../frontend/src/plugins/extensions.ts)
- [frontend/src/shared/lib/persistence.ts](../../frontend/src/shared/lib/persistence.ts)
- [src/resume_maker/plugin_packages/ext_ai_conversation/client/Chat.tsx](../../src/resume_maker/plugin_packages/ext_ai_conversation/client/Chat.tsx)
- [src/resume_maker/plugin_packages/ext_template_adapter/client/TemplateAdapter.tsx](../../src/resume_maker/plugin_packages/ext_template_adapter/client/TemplateAdapter.tsx)
- [src/resume_maker/plugin_packages/ext_word/client/templatePreviewQueue.ts](../../src/resume_maker/plugin_packages/ext_word/client/templatePreviewQueue.ts)
- [src/resume_maker/plugin_packages/sys_resume/client/features/experiences/useField.ts](../../src/resume_maker/plugin_packages/sys_resume/client/features/experiences/useField.ts)

### B16 · 证据状态、修订来源和隐私审计记录

证据与修订来源属于领域和隐私协议；有限审计属于固定保护策略，类型整理另行处理

- [frontend/src/shared/types/index.ts](../../frontend/src/shared/types/index.ts)
- [src/resume_maker/domain/models.py](../../src/resume_maker/domain/models.py)
- [src/resume_maker/integrations/privacy_gateway.py](../../src/resume_maker/integrations/privacy_gateway.py)
- [src/resume_maker/integrations/privacy_store.py](../../src/resume_maker/integrations/privacy_store.py)
- [src/resume_maker/integrations/sources.py](../../src/resume_maker/integrations/sources.py)
- [src/resume_maker/plugin_packages/sys_experience/services/catalog.py](../../src/resume_maker/plugin_packages/sys_experience/services/catalog.py)
- [src/resume_maker/plugin_packages/sys_experience/services/history.py](../../src/resume_maker/plugin_packages/sys_experience/services/history.py)
- [src/resume_maker/plugin_packages/sys_resume/client/features/experiences/EvidenceDialog.tsx](../../src/resume_maker/plugin_packages/sys_resume/client/features/experiences/EvidenceDialog.tsx)
- [src/resume_maker/plugin_packages/sys_resume/client/features/experiences/history.ts](../../src/resume_maker/plugin_packages/sys_resume/client/features/experiences/history.ts)
- [src/resume_maker/plugin_packages/sys_resume/client/features/settings/Privacy.tsx](../../src/resume_maker/plugin_packages/sys_resume/client/features/settings/Privacy.tsx)

### C01 · 响应分页与材料读取限制

响应分页和只读材料工具保留有界 SDK 或局部策略；字符、字节和集合限制不可混为一项

- [src/resume_maker/integrations/providers/material_server.py](../../src/resume_maker/integrations/providers/material_server.py)
- [src/resume_maker/integrations/providers/source_broker.py](../../src/resume_maker/integrations/providers/source_broker.py)
- [src/resume_maker/integrations/source_access.py](../../src/resume_maker/integrations/source_access.py)
- [src/resume_maker/plugin_packages/ext_ai_conversation/services/jobs.py](../../src/resume_maker/plugin_packages/ext_ai_conversation/services/jobs.py)
- [src/resume_maker/plugin_packages/sys_experience/services/projects.py](../../src/resume_maker/plugin_packages/sys_experience/services/projects.py)
- [src/resume_maker/plugin_packages/sys_resume/routes/resumes.py](../../src/resume_maker/plugin_packages/sys_resume/routes/resumes.py)
- [src/resume_maker/plugin_packages/sys_resume/services/resume_sources.py](../../src/resume_maker/plugin_packages/sys_resume/services/resume_sources.py)
- [src/resume_maker/plugin_packages/sys_resume/services/resumes.py](../../src/resume_maker/plugin_packages/sys_resume/services/resumes.py)
- [src/resume_maker/sdk/services.py](../../src/resume_maker/sdk/services.py)

### C02 · HTTP header、令牌meta和SDK资源路径

HTTP 身份与资源路径属于版本化宿主协议；不开放 token、Host、Origin 或任意 API 地址

- [frontend/index.html](../../frontend/index.html)
- [frontend/scripts/build-plugins.mjs](../../frontend/scripts/build-plugins.mjs)
- [frontend/scripts/sdk-loader.mjs](../../frontend/scripts/sdk-loader.mjs)
- [frontend/src/shared/lib/api.ts](../../frontend/src/shared/lib/api.ts)
- [frontend/src/shared/lib/capabilities.ts](../../frontend/src/shared/lib/capabilities.ts)
- [frontend/vite.config.ts](../../frontend/vite.config.ts)
- [scripts/stop.ps1](../../scripts/stop.ps1)
- [src/resume_maker/api/middleware.py](../../src/resume_maker/api/middleware.py)
- [src/resume_maker/api/plugin_dispatch.py](../../src/resume_maker/api/plugin_dispatch.py)
- [src/resume_maker/api/static.py](../../src/resume_maker/api/static.py)

### C03 · 目录与存储文件名

数据、前端和沙箱继续使用 core 目录入口；持久文件名保留兼容，目录不批量环境化

- [scripts/start.ps1](../../scripts/start.ps1)
- [scripts/stop.ps1](../../scripts/stop.ps1)
- [src/resume_maker/api/app.py](../../src/resume_maker/api/app.py)
- [src/resume_maker/candidate_host.py](../../src/resume_maker/candidate_host.py)
- [src/resume_maker/cli.py](../../src/resume_maker/cli.py)
- [src/resume_maker/core/config.py](../../src/resume_maker/core/config.py)
- [src/resume_maker/host_supervisor.py](../../src/resume_maker/host_supervisor.py)
- [src/resume_maker/plugin_packages/provider_sqlite/entry.py](../../src/resume_maker/plugin_packages/provider_sqlite/entry.py)

### C04 · 界面布局、断点与短时反馈

用户布局沿用存储和 CSS，组件尺寸保持局部；共享展示 token 可另行提取

- [frontend/src/shared/components/CopyButton.tsx](../../frontend/src/shared/components/CopyButton.tsx)
- [frontend/src/shared/components/PersistenceStatus.tsx](../../frontend/src/shared/components/PersistenceStatus.tsx)
- [frontend/src/shared/lib/activityPreferences.ts](../../frontend/src/shared/lib/activityPreferences.ts)
- [frontend/src/shared/lib/layout.ts](../../frontend/src/shared/lib/layout.ts)
- [frontend/src/styles/base.css](../../frontend/src/styles/base.css)
- [frontend/src/styles/components.css](../../frontend/src/styles/components.css)
- [frontend/src/styles/plugins.css](../../frontend/src/styles/plugins.css)
- [src/resume_maker/plugin_packages/ext_activity_ui/client/activity.css](../../src/resume_maker/plugin_packages/ext_activity_ui/client/activity.css)
- [src/resume_maker/plugin_packages/ext_honors/client/honors.css](../../src/resume_maker/plugin_packages/ext_honors/client/honors.css)
- [src/resume_maker/plugin_packages/ext_recruitment/client/recruitment.css](../../src/resume_maker/plugin_packages/ext_recruitment/client/recruitment.css)
- [src/resume_maker/plugin_packages/ext_template_adapter/client/TemplateAdapter.tsx](../../src/resume_maker/plugin_packages/ext_template_adapter/client/TemplateAdapter.tsx)
- [src/resume_maker/plugin_packages/ext_template_adapter/client/TemplateProgress.tsx](../../src/resume_maker/plugin_packages/ext_template_adapter/client/TemplateProgress.tsx)
- [src/resume_maker/plugin_packages/ext_template_adapter/client/templates.css](../../src/resume_maker/plugin_packages/ext_template_adapter/client/templates.css)
- [src/resume_maker/plugin_packages/ext_template_library/client/template-library.css](../../src/resume_maker/plugin_packages/ext_template_library/client/template-library.css)
- [src/resume_maker/plugin_packages/ext_workflow/client/workflow-density.css](../../src/resume_maker/plugin_packages/ext_workflow/client/workflow-density.css)
- [src/resume_maker/plugin_packages/sys_resume/client/features/resumes/ResumeWorkspace.tsx](../../src/resume_maker/plugin_packages/sys_resume/client/features/resumes/ResumeWorkspace.tsx)
- [src/resume_maker/plugin_packages/sys_resume/client/styles/defaults.css](../../src/resume_maker/plugin_packages/sys_resume/client/styles/defaults.css)
- [src/resume_maker/plugin_packages/sys_resume/client/styles/history.css](../../src/resume_maker/plugin_packages/sys_resume/client/styles/history.css)
- [src/resume_maker/plugin_packages/sys_resume/client/styles/privacy.css](../../src/resume_maker/plugin_packages/sys_resume/client/styles/privacy.css)
- [src/resume_maker/plugin_packages/sys_resume/client/styles/profile.css](../../src/resume_maker/plugin_packages/sys_resume/client/styles/profile.css)
- [src/resume_maker/plugin_packages/sys_resume/client/styles/responsive.css](../../src/resume_maker/plugin_packages/sys_resume/client/styles/responsive.css)
- [src/resume_maker/plugin_packages/sys_resume/client/styles/resume-library.css](../../src/resume_maker/plugin_packages/sys_resume/client/styles/resume-library.css)
- [src/resume_maker/plugin_packages/sys_resume/client/styles/settings.css](../../src/resume_maker/plugin_packages/sys_resume/client/styles/settings.css)
- [src/resume_maker/plugin_packages/sys_resume/client/styles/workspace.css](../../src/resume_maker/plugin_packages/sys_resume/client/styles/workspace.css)
- [src/resume_maker/plugin_packages/sys_workbench/client/features/plugins/plugin-manager.css](../../src/resume_maker/plugin_packages/sys_workbench/client/features/plugins/plugin-manager.css)

### C05 · Word主题、单位、XML命名空间和COM枚举

OOXML 单位、命名空间及 COM 编号属于固定格式标准；另行按文档职责命名，字体仍按平台回退

- [src/resume_maker/integrations/word/full_resume.py](../../src/resume_maker/integrations/word/full_resume.py)
- [src/resume_maker/integrations/word/image/layout.py](../../src/resume_maker/integrations/word/image/layout.py)
- [src/resume_maker/integrations/word/ooxml.py](../../src/resume_maker/integrations/word/ooxml.py)
- [src/resume_maker/integrations/word/pdf/assets.py](../../src/resume_maker/integrations/word/pdf/assets.py)
- [src/resume_maker/integrations/word/pdf/flow.py](../../src/resume_maker/integrations/word/pdf/flow.py)
- [src/resume_maker/integrations/word/pdf/geometry.py](../../src/resume_maker/integrations/word/pdf/geometry.py)
- [src/resume_maker/integrations/word/pdf/header_items.py](../../src/resume_maker/integrations/word/pdf/header_items.py)
- [src/resume_maker/integrations/word/pdf/header_layout.py](../../src/resume_maker/integrations/word/pdf/header_layout.py)
- [src/resume_maker/integrations/word/pdf/recovery.py](../../src/resume_maker/integrations/word/pdf/recovery.py)
- [src/resume_maker/integrations/word/recovery.py](../../src/resume_maker/integrations/word/recovery.py)
- [src/resume_maker/integrations/word/templates/anchors.py](../../src/resume_maker/integrations/word/templates/anchors.py)
- [src/resume_maker/integrations/word/templates/contact_style.py](../../src/resume_maker/integrations/word/templates/contact_style.py)
- [src/resume_maker/integrations/word/templates/fill.py](../../src/resume_maker/integrations/word/templates/fill.py)
- [src/resume_maker/integrations/word/templates/flow.py](../../src/resume_maker/integrations/word/templates/flow.py)
- [src/resume_maker/integrations/word/templates/layout.py](../../src/resume_maker/integrations/word/templates/layout.py)
- [src/resume_maker/integrations/word/templates/mapping.py](../../src/resume_maker/integrations/word/templates/mapping.py)
- [src/resume_maker/integrations/word/templates/personal.py](../../src/resume_maker/integrations/word/templates/personal.py)
- [src/resume_maker/integrations/word/templates/prepare.py](../../src/resume_maker/integrations/word/templates/prepare.py)
- [src/resume_maker/integrations/word/templates/project_order.py](../../src/resume_maker/integrations/word/templates/project_order.py)
- [src/resume_maker/plugin_packages/ext_word/integrations/word/worker.py](../../src/resume_maker/plugin_packages/ext_word/integrations/word/worker.py)

### C06 · 材料策略、进程控制和提示词资源

权限、只读工具、敏感过滤和输出预算保持代码策略；源码 Git 和 CLI 探测等待已配置化，提示词资源可另行整理

- [src/resume_maker/integrations/privacy.py](../../src/resume_maker/integrations/privacy.py)
- [src/resume_maker/integrations/providers/credentials.py](../../src/resume_maker/integrations/providers/credentials.py)
- [src/resume_maker/integrations/providers/material_server.py](../../src/resume_maker/integrations/providers/material_server.py)
- [src/resume_maker/integrations/providers/page_images.py](../../src/resume_maker/integrations/providers/page_images.py)
- [src/resume_maker/integrations/providers/process.py](../../src/resume_maker/integrations/providers/process.py)
- [src/resume_maker/integrations/providers/sandbox.py](../../src/resume_maker/integrations/providers/sandbox.py)
- [src/resume_maker/integrations/source_context.py](../../src/resume_maker/integrations/source_context.py)
- [src/resume_maker/integrations/sources.py](../../src/resume_maker/integrations/sources.py)
- [src/resume_maker/integrations/word/image/recovery.py](../../src/resume_maker/integrations/word/image/recovery.py)
- [src/resume_maker/integrations/word/recovery.py](../../src/resume_maker/integrations/word/recovery.py)
- [src/resume_maker/plugin_packages/ext_provider_codex/integrations/providers/cli.py](../../src/resume_maker/plugin_packages/ext_provider_codex/integrations/providers/cli.py)
- [src/resume_maker/plugin_packages/ext_provider_codex/integrations/providers/model_catalog.py](../../src/resume_maker/plugin_packages/ext_provider_codex/integrations/providers/model_catalog.py)

### C07 · 构建版本、包依赖范围和生成校验

依赖、协议和产品版本保持清单及锁文件；运行配置生成校验已接入完整检查

- [.github/workflows/ci.yml](../../.github/workflows/ci.yml)
- [.node-version](../../.node-version)
- [.python-version](../../.python-version)
- [frontend/package.json](../../frontend/package.json)
- [pyproject.toml](../../pyproject.toml)
- [scripts/build_hook.py](../../scripts/build_hook.py)
- [scripts/check.py](../../scripts/check.py)
- [scripts/check_quality.py](../../scripts/check_quality.py)
- [src/resume_maker/__init__.py](../../src/resume_maker/__init__.py)
- [src/resume_maker/plugin_packages/provider_rapidocr/manifest.json](../../src/resume_maker/plugin_packages/provider_rapidocr/manifest.json)

## 验证边界

配置验收使用合成资料、临时数据库和替身进程，覆盖文件输入、旧空配置、保存后重启、无效配置拒绝、OCR 实例隔离及后端限制元数据。Word 超时参数通过替身验证；未对真实个人文档执行 Word 或调用真实模型。完整检查、wheel 和最小依赖安装按仓库规定执行，实际结果记录在 PR。
