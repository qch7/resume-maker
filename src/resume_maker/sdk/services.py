"""Host API 1.0 的领域服务协议，签名变更须同步契约兼容测试"""

from pathlib import Path
from typing import Protocol

from resume_maker.domain.honors import HonorSave
from resume_maker.domain.models import ProjectProfile, ProviderSettings, ResumeItem
from resume_maker.domain.recruitment import RecruitmentFile, RecruitmentPreferences
from resume_maker.domain.resume import ResumeDocument
from resume_maker.domain.resume_defaults import ResumeDefaults
from resume_maker.domain.templates import TemplatePlan


class History(Protocol):
    """History 的公开业务操作，插件消费者不依赖具体实现"""

    def branches(self, project_id: str) -> list[dict]:
        """列出项目分支，主分支优先，其余按创建时间稳定排序"""
        ...

    def for_revision(self, project_id: str, revision_id: str) -> dict:
        """定位修订所属分支，同时拒绝跨项目引用"""
        ...

    def initialize(self, conn, project_id: str, revision_id: str, stamp: str) -> None:
        """为新项目的初始修订登记 main，和项目创建原子完成"""
        ...

    def advance(self, conn, branch: dict, revision_id: str, stamp: str) -> None:
        """移动目标分支指针并更新项目活动时间，其他分支保持不变"""
        ...

    def create(self, project_id: str, revision_id: str, name: str, include_drafts: bool) -> dict:
        """从任意保存版本创建分支起点，可复制草稿但不会把草稿隐式发布"""
        ...


class Catalog(Protocol):
    """Catalog 的公开业务操作，插件消费者不依赖具体实现"""

    history: History

    def workspace_state(self, conn):
        """在调用方快照内返回模块拥有的工作台查询"""
        ...

    def on_project_created(self, owner, initialize):
        """登记项目创建事务内的扩展初始化并返回撤销函数"""
        ...

    def branch(self, project_id, revision_id):
        """读取不可变修订所属分支"""
        ...

    def apply_suggestion(self, conn, project_id, revision_id, field, before, after, snapshot_id):
        """在同一写事务核验分支和原文后应用建议草稿"""
        ...

    def publish_evidence(self, project_id, identifier, fingerprint, manifest, files):
        """原子发布固定证据和不可变资源引用"""
        ...

    def project(self, project_id: str) -> dict:
        """读取项目并在记录缺失时抛出业务异常"""
        ...

    def revision(self, revision_id: str, project_id: str | None = None, conn=None) -> dict:
        """读取不可变经历版本并按需验证它属于指定项目"""
        ...

    def create_project(self, name: str, roots: list[str]) -> dict:
        """规范化来源并去重登记项目，同时建立初始经历和已注册的扩展资料"""
        ...

    def sync_subprojects(self, project_id: str) -> None:
        """来源变更后幂等更新整体项目的子项目关联"""
        ...

    def working(self, project_id: str, revision_id: str) -> dict:
        """按覆盖优先级将草稿叠加在固定版本上，返回可编辑工作副本"""
        ...

    def put_draft(self, project_id: str, revision_id: str, field: str, value, version: int):
        """校验字段并按草稿版本写入，拒绝覆盖其他窗口的新修改"""
        ...

    def discard_draft(self, project_id: str, revision_id: str, field: str, version: int):
        """确认草稿版本仍匹配后删除指定字段的未发布修改"""
        ...

    def discard_drafts(self, project_id: str, revision_id: str, versions: dict[str, int]):
        """在同一事务中核对并撤销当前项目和基线的完整草稿集合"""
        ...

    def save_revision(self, project_id: str, revision_id: str, expected_head: str) -> dict:
        """校验分支头和草稿版本后发布整个工作副本，原子清理已提交草稿"""
        ...

    def restore(self, project_id: str, revision_id: str, expected_head: str) -> dict:
        """在历史版本所属分支追加恢复版本，保留来源快照及已有版本链"""
        ...


class Projects(Protocol):
    """Projects 的公开业务操作，插件消费者不依赖具体实现"""

    def get_project(self, project_id: str, revision_id: str | None = None):
        """读取选定版本的工作副本、历史修订和来源快照供经历编辑器展示"""
        ...

    def delete(self, project_id: str) -> list[str]:
        """同一事务内检查简历引用和运行任务后删除项目组，不访问源码或历史导出文件"""
        ...

    def uncommitted(self, project_id: str) -> list[dict]:
        """列出各版本存在实际修改的工作副本供历史树展示"""
        ...

    def save_profile(self, project_id: str, profile: ProjectProfile):
        """保存用户确认的角色、日期和贡献信息并更新项目活动时间"""
        ...

    def update_sources(self, project_id: str, name: str, sources: list[str]):
        """校验并重新绑定项目来源目录，保留已经生成的经历和历史"""
        ...

    def source_path(self, project_id: str, snapshot_id: str, source: str, path: str) -> Path:
        """按历史快照解析来源，拒绝越界路径和已移走的文件以免打开错误仓库"""
        ...


class Resumes(Protocol):
    """Resumes 的公开业务操作，插件消费者不依赖具体实现"""

    def workspace_state(self, conn):
        """在调用方快照内返回模块拥有的工作台查询"""
        ...

    def template_bytes(self, template):
        """读取不可变模板原件，不向消费者暴露持久文件位置"""
        ...

    def freeze_export(self, directory, identifier, expected_version=None):
        """固定同一事务快照中的简历、修订和模板输入"""
        ...

    def freeze_preview(self, directory, template_id, document, items):
        """固定工作副本及其不可变引用"""
        ...

    def template_usage(self, conn, identifier):
        """在同一维护事务内返回模板的已保存方案引用"""
        ...

    def source_catalog(self):
        """列出已启用的资料来源"""
        ...

    def source_items(self, provider, cursor=None, query="", limit=50):
        """读取来源的有界资料页"""
        ...

    def preserve_sources(self, conn=None):
        """同一业务事务内保存最后核对的来源内容"""
        ...

    def revision(self, revision_id, project_id=None, conn=None):
        """核对不可变版本归属，不读取经历服务的内部状态"""
        ...

    def resolve_document(self, document, conn=None):
        """只通过已注册的来源解析器刷新内容，停用后保留确认快照"""
        ...

    def template(self, template_id: str, include_trashed: bool = False, conn=None) -> dict:
        """只允许引用具有完整映射的模板，失效引用由用户重新选择或识别"""
        ...

    def save_resume(
        self,
        name: str,
        template_id: str | None,
        items: list[ResumeItem],
        resume_id: str | None = None,
        version: int = 0,
        document: ResumeDocument | None = None,
    ) -> dict:
        """校验项目、版本和亮点归属并以乐观锁保存固定版本组合"""
        ...

    def delete_resume(self, resume_id: str, version: int) -> None:
        """按版本删除方案，保留项目、模板及历史导出，拒绝覆盖其他窗口的修改"""
        ...


class Conversations(Protocol):
    """Conversations 的公开业务操作，插件消费者不依赖具体实现"""

    def archived_conversations(self):
        """按最近更新时间列出归档会话，供设置界面恢复使用"""
        ...

    def get_conversation(self, conversation_id: str):
        """聚合单个会话的消息、建议和任务，保持不同会话上下文隔离"""
        ...

    def patch_conversation(self, conversation_id: str, values: dict):
        """更新允许编辑的会话字段且仅在值变化时刷新活动时间"""
        ...

    def rebuild_conversation(self, conversation_id: str):
        """确认没有活动任务后清除模型会话标识，下轮使用保存的历史重建"""
        ...

    def create_conversation(self, project_id: str, title: str) -> dict:
        """为指定项目创建具有独立历史和输入草稿的会话"""
        ...

    def conversation(self, conversation_id: str) -> dict:
        """读取会话并在记录缺失时抛出业务异常"""
        ...

    def adopt(self, proposal_id: str):
        """检查建议原文和当前内容一致后写入草稿以免覆盖后续人工编辑"""
        ...

    def initialize_project(self, conn, project_id, stamp):
        """在经历建立事务内初始化会话，插件卸载后撤销此贡献"""
        ...


class Jobs(Protocol):
    """Jobs 的公开业务操作，插件消费者不依赖具体实现"""

    @property
    def event_poll_seconds(self) -> float:
        """进度流消费任务所有者发布的有效检查间隔"""
        ...

    def submit(
        self,
        conversation_id: str,
        text: str,
        kind: str,
        revision_id: str,
        scope: str,
        request_key: str,
    ) -> dict:
        """校验会话和编辑范围，以幂等请求标识入队并记录用户消息"""
        ...

    def cancel(self, job_id: str):
        """同时更新持久状态和进程取消信号，阻止任务结果继续发布"""
        ...


class Honors(Protocol):
    """Honors 的公开业务操作，插件消费者不依赖具体实现"""

    def attach_recognition(self, provider, execution_queue, recognition):
        """附接识别处理器，撤销等待实际任务和资源清理结束"""
        ...

    def file_reference(self, identifier, page=None):
        """返回登记的资源标识和文件名，读取者须持有资源租约"""
        ...

    def list(self):
        """返回独立荣誉条目，按最近更新排列"""
        ...

    def get(self, identifier, conn=None):
        """只读取合法荣誉标识以免附件路径被任意输入控制"""
        ...

    def save(self, body: HonorSave, identifier=None):
        """保存人工填写和核对后的完整字段，识别中和版本过期时拒绝覆盖"""
        ...

    def upload(self, raw, filename, importer_id=None):
        """完整校验并保存原件后创建待识别条目，失败上传不留下半条记录"""
        ...

    def recognize(self, identifier):
        """固化当前识别配置并入队，重复操作或尚未回收的旧任务被拒绝"""
        ...

    def cancel(self, identifier):
        """立即标记取消，后台迟到结果不能覆盖人工编辑"""
        ...

    def delete(self, identifier, version):
        """删除库条目并取消识别，关联简历保留删除前最后核对的资料"""
        ...


class Documents(Protocol):
    """Documents 的公开业务操作，插件消费者不依赖具体实现"""

    def engines(self) -> dict:
        """列出当前已注册的文档引擎及渲染器"""
        ...

    def importers(self, purpose) -> list[dict]:
        """列出当前可选的文件处理器和支持格式"""
        ...

    def export(
        self, resume_id: str, *, expected_version=None, engine_id=None, renderer_id=None
    ) -> dict:
        """读取固定资料及项目引用，按所选完整模板或内置版式生成文件和清单"""
        ...


class ResumePreviews(Protocol):
    """ResumePreviews 的公开业务操作，插件消费者不依赖具体实现"""

    def maintenance(self):
        """返回阻止迟到预览生成的维护屏障"""
        ...

    def template_artifacts(self, template_id):
        """返回目标模板的可清理预览路径"""
        ...

    def invalidate_template(self, template_id):
        """撤销已清理模板的预览缓存"""
        ...

    def render(self, template_id, document, items, *, engine_id=None, renderer_id=None):
        """核验固定版本归属后使用当前资料和可选工作副本试填"""
        ...

    def file(self, identifier, filename):
        """只提供当前实例已生成的预览文件，模板源文件和任意路径均不可下载"""
        ...

    def lease(self, identifier, filename):
        """返回覆盖完整文件传输的临时预览租约"""
        ...


class Settings(Protocol):
    """Settings 的公开业务操作，插件消费者不依赖具体实现"""

    def workspace_state(self, conn):
        """在调用方快照内返回模块拥有的工作台查询"""
        ...

    def get(self):
        """返回完整 Provider 配置和当前数据目录"""
        ...

    def save_provider(self, settings: ProviderSettings):
        """保存已校验的模型参数，后续任务读取新的配置"""
        ...

    def recruitment(self):
        """读取收藏夹导入偏好，首次使用时保留本机重复项"""
        ...

    def save_recruitment(self, settings: RecruitmentPreferences):
        """保存收藏夹偏好，重新打开导入窗口时读取最新配置"""
        ...

    def resume_defaults(self):
        """读取默认栏目，尚未设置时由前端提供初始配置"""
        ...

    def save_resume_defaults(self, defaults: ResumeDefaults):
        """在同一事务内校验版本和保存默认栏目，防止多窗口覆盖"""
        ...

    def attach_provider(self, provider):
        """附接模型出口并返回撤销函数"""
        ...

    def check_provider(self):
        """通过统一隐私出口验证独立连接配置，保留真实结构化响应"""
        ...


class Privacy(Protocol):
    """Privacy 的公开业务操作，插件消费者不依赖具体实现"""

    def get(self):
        """返回强制隐私策略和用户可补充的敏感词"""
        ...

    def save_terms(self, terms: list[str], expected_version: int):
        """同一事务内保存规范化敏感词和版本，冲突时保留原有设置"""
        ...

    def preview(self, text: str):
        """只在内存中预览脱敏结果，不保存原文和还原表"""
        ...

    def requests(self):
        """读取已脱敏的发送记录，不包含响应原文和真实值映射"""
        ...

    def clear_requests(self):
        """清除当前实例的发送记录，保留敏感词及简历资料"""
        ...


class Recruitment(Protocol):
    """Recruitment 的公开业务操作，插件消费者不依赖具体实现"""

    def get(self):
        """首次访问返回空收藏夹，企业清单由用户主动导入"""
        ...

    def save(self, revision: int, data: RecruitmentFile):
        """保存用户编辑后的完整收藏夹，版本核验和写入处于同一事务"""
        ...

    def import_file(self, revision: int, content: str, policy, *, preview: bool):
        """预览只计算变化，确认导入时重新校验版本并原子合并"""
        ...


class Workspace(Protocol):
    """Workspace 的公开业务操作，插件消费者不依赖具体实现"""

    def state(self):
        """保持经历活动时间、简历来源和各插件摘要的事务一致性"""
        ...


class WorkspaceStorage(Protocol):
    """WorkspaceStorage 的公开业务操作，插件消费者不依赖具体实现"""

    def state(self):
        """启动时读取持久草稿，包含删除版本以检查浏览器未完成写入"""
        ...

    def save(self, key, value, version):
        """在同一事务内比较版本，重复请求幂等，删除同样推进版本"""
        ...


class TemplateLibrary(Protocol):
    """TemplateLibrary 的公开业务操作，插件消费者不依赖具体实现"""

    def state(self):
        """返回组织信息，未设置的模板由客户端归入未分类"""
        ...

    def update(self, template_id, changes):
        """原子修改名称和组织信息，保持模板标识、映射、文件及简历引用不变"""
        ...

    def delete(self, template_id, permanent=False, cutoff=None):
        """拒绝删除被引用的模板，默认移入回收站，永久删除同步清理文件及数据库"""
        ...

    def restore(self, template_id):
        """在写事务中恢复模板及原分类收藏以排除到期清理竞争"""
        ...

    def purge_expired(self, at=None):
        """逐项清理满三十天的模板，单项占用或文件错误留待下次重试"""
        ...

    def create_category(self, name):
        """创建名称非空且唯一的分类"""
        ...

    def delete_category(self, category_id):
        """移除分类时将其中模板归回未分类，保留模板、收藏和简历引用"""
        ...

    def thumbnail(self, template_id):
        """渲染源模板首屏并缓存，不试填个人资料、不登记导出、不调用 AI"""
        ...


class Templates(Protocol):
    """Templates 的公开业务操作，插件消费者不依赖具体实现"""

    def maintenance(self):
        """返回阻止新任务和保存交错的维护屏障"""
        ...

    def cleanup_paths(self, template_id, shared):
        """核验没有在途任务后返回可清理路径"""
        ...

    def invalidate_artifacts(self, conn, paths):
        """同事务撤销已清理任务和资源引用"""
        ...

    def list_tasks(self):
        """列出可恢复的模板工作，已保存版本仍在独立模板库中"""
        ...

    def retry(self, identifier, document, items):
        """使用留存原件显式重试中断任务，不在启动时自动发送模型请求"""
        ...

    def attach_analysis(self, provider, execution_queue, analysis):
        """附接分析处理器，撤销时等待实际任务结束"""
        ...

    def analyze(
        self,
        path: Path,
        document: ResumeDocument,
        items: list[ResumeItem] | None = None,
        *,
        importer_id=None,
    ) -> dict:
        """先复制源文档为受控快照，再异步分析，源文件后续变化不影响确认结果"""
        ...

    def repair(self, identifier, plan, document, items, feedback=""):
        """根据当前人工方案新建独立修正任务"""
        ...

    def get(self, identifier: str) -> dict:
        """读取可跨服务重启恢复的分析结果"""
        ...

    def progress(self, identifier, after=0):
        """仅返回任务进度和游标之后的活动"""
        ...

    def open(self, template_id: str, document=None, items=None) -> dict:
        """按当前资料补齐独立编辑快照"""
        ...

    def cancel(self, identifier: str) -> dict:
        """取消尚未结束的分析，迟到的模型结果不能重新发布"""
        ...

    def source(self, identifier: str) -> Path:
        """确认任务属于当前实例且分析完成，再取得内部快照路径"""
        ...

    def review(
        self,
        identifier: str,
        plan: TemplatePlan,
        document: ResumeDocument | None = None,
        items: list[ResumeItem] | None = None,
    ) -> dict:
        """在内存副本中按导出规则补位并校验"""
        ...

    def save(
        self,
        identifier: str,
        name: str,
        plan: TemplatePlan,
        document: ResumeDocument,
        items: list[ResumeItem],
    ) -> dict:
        """登记核对过的完整模板，原文件和映射一并保留供重复导出和备份"""
        ...

    def preview(
        self, identifier: str, plan: TemplatePlan, document: ResumeDocument, items: list[ResumeItem]
    ) -> dict:
        """使用当前资料试填，校验固定引用和选择后生成 Word 和可用的分页预览"""
        ...

    def projects(self, items: list[ResumeItem]) -> list[dict]:
        """校验固定项目和亮点引用，保存和试填使用同一份资料覆盖规则"""
        ...

    def preview_lease(self, identifier, preview_id, filename):
        """返回核对分析归属的试填文件租约"""
        ...


class SourceAccess(Protocol):
    """源码插件公开能力，停用后不再扫描或传递源码材料"""

    def scan(self, path: Path):
        """扫描用户选择的目录并列出项目分组"""
        ...

    def describe(self, project):
        """读取项目绑定的来源描述"""
        ...

    def context(self, sources, cancelled):
        """建立有界只读材料上下文"""
        ...

    def capture(self, project, sources, references, cancelled):
        """按实际引用核对并保存不可变证据"""
        ...

    def check(self, snapshot, evidence):
        """依据保留原件校验行号和引文"""
        ...
