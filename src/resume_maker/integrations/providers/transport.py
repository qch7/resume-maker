"""无工具 Responses 请求，限定体积、超时和取消，不执行返回的工具调用"""

import asyncio
import json

import httpx

from resume_maker.integrations.providers.base import Cancelled, ProviderError

MAX_BYTES = 4 * 1024 * 1024


async def request(url, key, payload, timeout, cancelled, transport=None):
    """通过可取消异步连接读取有界响应，错误内容不写入日志"""
    async with httpx.AsyncClient(
        transport=transport, follow_redirects=False, timeout=timeout
    ) as client:

        async def send():
            """一次发送且不自动回退供应商、原文或其他协议"""
            async with client.stream(
                "POST", url, headers={"Authorization": "Bearer " + key}, json=payload
            ) as response:
                if response.status_code != 200:
                    raise ProviderError(
                        f"模型服务返回 HTTP {response.status_code}，请检查连接配置。"
                    )
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > MAX_BYTES:
                        raise ProviderError("模型响应超过大小限制，已停止接收。")
                try:
                    return json.loads(raw)
                except ValueError as exc:
                    raise ProviderError("模型服务没有返回有效 JSON。") from exc

        task = asyncio.create_task(send())
        try:
            async with asyncio.timeout(timeout):
                while not task.done():
                    if cancelled.is_set():
                        raise Cancelled("请求已取消。")
                    await asyncio.wait({task}, timeout=0.05)
                if cancelled.is_set():
                    raise Cancelled("请求已取消。")
                return await task
        except (TimeoutError, httpx.HTTPError) as exc:
            raise ProviderError("模型连接失败或超时，请检查供应商配置后重试。") from exc
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)


def response_text(response, emit):
    """仅接受完成的文字消息，工具请求和拒绝都不作为结构化结果发布"""
    if not isinstance(response, dict) or response.get("status") != "completed":
        raise ProviderError("模型请求未完整完成，结果未采用。")
    texts = []
    output = response.get("output")
    if not isinstance(output, list):
        raise ProviderError("模型响应缺少有效输出列表。")
    for item in output:
        if not isinstance(item, dict):
            raise ProviderError("模型响应条目格式无效。")
        if item.get("type") == "reasoning":
            continue
        if item.get("type") != "message":
            raise ProviderError("隐私保护拒绝模型工具请求，未执行任何工具。")
        content = item.get("content")
        if not isinstance(content, list):
            raise ProviderError("模型消息内容格式无效。")
        for part in content:
            if (
                not isinstance(part, dict)
                or part.get("type") != "output_text"
                or not isinstance(part.get("text"), str)
            ):
                raise ProviderError("模型未返回可用的文字结果。")
            texts.append(part["text"])
    usage = response.get("usage") or {}
    if isinstance(usage, dict):
        emit(
            "usage",
            {
                key: value
                for key in ("input_tokens", "output_tokens")
                if isinstance(value := usage.get(key), int) and value >= 0
            },
        )
    return "".join(texts)
