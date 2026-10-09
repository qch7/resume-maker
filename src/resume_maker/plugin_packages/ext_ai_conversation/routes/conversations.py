"""独立会话维护和消息提交的 HTTP 入口"""

from typing import Annotated

from fastapi import APIRouter, Depends

from resume_maker.api.dependencies import service
from resume_maker.api.schemas import ConversationInput, MessageInput
from resume_maker.sdk.services import Conversations, Jobs

router = APIRouter(prefix="/api", tags=["conversations"])


@router.post("/projects/{project_id}/conversations")
def create_conversation(
    dep_conversations: Annotated[Conversations, Depends(service("conversations"))], project_id: str
):
    """为指定项目创建具有独立历史和输入草稿的会话"""
    return dep_conversations.create_conversation(project_id, "新会话")


@router.get("/conversations/archived")
def archived_conversations(
    dep_conversations: Annotated[Conversations, Depends(service("conversations"))],
):
    """按最近更新时间列出归档会话，供设置界面恢复使用"""
    return dep_conversations.archived_conversations()


@router.get("/conversations/{conversation_id}")
def get_conversation(
    dep_conversations: Annotated[Conversations, Depends(service("conversations"))],
    conversation_id: str,
):
    """聚合单个会话的消息、建议和任务，保持不同会话上下文隔离"""
    return dep_conversations.get_conversation(conversation_id)


@router.patch("/conversations/{conversation_id}")
def patch_conversation(
    dep_conversations: Annotated[Conversations, Depends(service("conversations"))],
    conversation_id: str,
    body: ConversationInput,
):
    """更新允许编辑的会话字段且仅在值变化时刷新活动时间"""
    return dep_conversations.patch_conversation(conversation_id, body.model_dump(exclude_none=True))


@router.post("/conversations/{conversation_id}/rebuild")
def rebuild_conversation(
    dep_conversations: Annotated[Conversations, Depends(service("conversations"))],
    conversation_id: str,
):
    """确认没有活动任务后清除模型会话标识，下轮使用保存的历史重建"""
    return dep_conversations.rebuild_conversation(conversation_id)


@router.post("/conversations/{conversation_id}/messages")
def message(
    dep_jobs: Annotated[Jobs, Depends(service("jobs"))], conversation_id: str, body: MessageInput
):
    """将用户消息及版本、范围、幂等标识提交至持久任务队列"""
    return dep_jobs.submit(
        conversation_id, body.text, body.kind, body.base_revision, body.scope, body.request_key
    )
