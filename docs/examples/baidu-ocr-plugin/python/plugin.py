"""通过公开 SDK 提供百度云 OCR，不依赖宿主或其他插件的私有实现"""

import base64
import hashlib
import json
import math
import threading
import time
from contextlib import contextmanager
from http.client import HTTPException
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

import pymupdf
from PIL import Image, ImageOps
from resume_maker.sdk.context import Context, ServiceKey
from resume_maker.sdk.model import Cancelled, ProviderError

PLUGIN_ID = "community.baidu-ocr"
TOKEN_URL = "https://aip.baidubce.com/oauth/2.0/token"
OCR_URL = "https://aip.baidubce.com/rest/2.0/ocr/v1/"
MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_FORM_BYTES = 10 * 1024 * 1024
MAX_PAGES, MAX_PIXELS, MAX_BLOCKS, MAX_TEXT = 12, 40_000_000, 6000, 100_000
REVIEW_SCORE = 0.85


class RejectRedirects(HTTPRedirectHandler):
    """拒绝把鉴权参数或图像转发给重定向目标"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        """固定官方服务目的地并停止重定向"""
        raise ProviderError("百度接口返回重定向，请检查网络配置。")


class Transport:
    """使用标准库发送有界 HTTPS 请求，异常不回显凭据或图像"""

    def __init__(self):
        """每个插件实例持有自己的连接策略"""
        self.opener = build_opener(RejectRedirects())

    def post(self, url, fields, timeout):
        """发送表单并限制响应大小，不自动重试可能计费的请求"""
        body = urlencode(fields).encode("ascii")
        if len(body) > MAX_FORM_BYTES:
            raise ProviderError("百度 OCR 请求超过 10 MB，请缩小图片。")
        request = Request(url, body, {"Content-Type": "application/x-www-form-urlencoded"})
        status = 200
        try:
            try:
                response = self.opener.open(request, timeout=timeout)
            except HTTPError as exc:
                response, status = exc, exc.code
            with response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except (OSError, URLError, TimeoutError, HTTPException):
            raise ProviderError("百度 OCR 网络请求失败或超时，请检查连接后重试。") from None
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ProviderError("百度 OCR 响应超过处理上限。")
        try:
            value = json.loads(raw)
        except (ValueError, UnicodeError):
            raise ProviderError(f"百度 OCR 返回无效响应（HTTP {status}）。") from None
        if not isinstance(value, dict):
            raise ProviderError("百度 OCR 返回了无效的数据结构。")
        if status != 200 and "error_code" not in value and "error" not in value:
            raise ProviderError(f"百度 OCR 请求失败（HTTP {status}）。")
        return value


@contextmanager
def load_credentials(filename):
    """从外部凭据文件短暂读取密钥，不写入插件配置或资料备份"""
    if not filename:
        raise ProviderError("请在百度 OCR 插件配置中设置凭据文件的绝对路径。")
    path = Path(filename).expanduser()
    if not path.is_absolute():
        raise ProviderError("百度 OCR 凭据文件必须使用绝对路径。")
    try:
        with path.open("rb") as stream:
            raw = stream.read(16_385)
        if len(raw) > 16_384:
            raise ValueError
        value = json.loads(raw.decode("utf-8-sig"))
        if not isinstance(value, dict) or set(value) != {"api_key", "secret_key"}:
            raise ValueError
        if any(
            not isinstance(item, str) or not item.strip() or len(item) > 1024
            for item in value.values()
        ):
            raise ValueError
    except (OSError, ValueError, UnicodeError):
        raise ProviderError(
            "百度 OCR 凭据文件不可读或格式错误，需要 api_key 和 secret_key。"
        ) from None
    yield value


def number(value):
    """只接受有限数值，避免错误坐标进入版面恢复"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProviderError("百度 OCR 返回了无效的坐标或置信度。")
    try:
        converted = float(value)
    except OverflowError:
        raise ProviderError("百度 OCR 返回了超出范围的坐标或置信度。") from None
    if not math.isfinite(converted):
        raise ProviderError("百度 OCR 返回了无效的坐标或置信度。")
    return converted


def convert_blocks(result, width, height):
    """把百度像素矩形转换成宿主消费的比例坐标和行置信度"""
    rows = result.get("words_result")
    if not isinstance(rows, list) or len(rows) > MAX_BLOCKS:
        raise ProviderError("百度 OCR 返回了无效或过多的文字行。")
    blocks = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("words"), str):
            raise ProviderError("百度 OCR 返回了无效的文字行。")
        text = row["words"].strip()
        if not text:
            continue
        rect = row.get("location")
        if not isinstance(rect, dict):
            raise ProviderError("百度 OCR 未返回位置，请开通含位置版接口。")
        try:
            left, top, box_width, box_height = (
                number(rect[key]) for key in ("left", "top", "width", "height")
            )
        except KeyError:
            raise ProviderError("百度 OCR 返回的文字位置不完整。") from None
        if left < 0 or top < 0 or box_width <= 0 or box_height <= 0:
            raise ProviderError("百度 OCR 返回了无效的文字范围。")
        box = [left / width, top / height, (left + box_width) / width, (top + box_height) / height]
        box = [min(1.0, max(0.0, item)) for item in box]
        if box[0] >= box[2] or box[1] >= box[3]:
            raise ProviderError("百度 OCR 文字位置超出图片范围。")
        probability = row.get("probability", {})
        if not isinstance(probability, dict):
            raise ProviderError("百度 OCR 返回了无效的置信度。")
        # 缺失置信度时保守标为待复核，避免把未知值当成准确识别
        confidence = number(probability.get("average", 0.0))
        if not 0 <= confidence <= 1:
            raise ProviderError("百度 OCR 返回了超出范围的置信度。")
        blocks.append({"text": text, "box": box, "confidence": round(confidence, 4)})
    return blocks


def native_blocks(page):
    """提取 PDF 可见文字的行位置，可靠文字页不调用计费接口"""
    if any(span.get("type") == 3 for span in page.get_texttrace()):
        return []
    blocks = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            text = "".join(span["text"] for span in line["spans"]).strip()
            if text and "\ufffd" not in text:
                left, top, right, bottom = pymupdf.Rect(line["bbox"]) * page.rotation_matrix
                box = [
                    left / page.rect.width,
                    top / page.rect.height,
                    right / page.rect.width,
                    bottom / page.rect.height,
                ]
                box = [min(1.0, max(0.0, item)) for item in box]
                if box[0] < box[2] and box[1] < box[3]:
                    blocks.append({"text": text, "box": box, "confidence": 1.0})
    return blocks


def overlaps(left, right):
    """从混合 PDF 页面中排除已经由文字层提供的重复识别行"""
    a, b = left["box"], right["box"]
    area = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
    return area > 0.3 * min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))


class BaiduOCR:
    """插件独立拥有令牌、串行请求及停止屏障"""

    def __init__(self, config, credentials, reference, transport=None):
        """冻结实例配置，网络仅在识别或手动连接检查时调用"""
        self.config = dict(config)
        self.credentials, self.reference = credentials, reference
        self.transport = transport or Transport()
        self.lock = threading.Lock()
        self.stopping = threading.Event()
        self.running = False
        self.token, self.token_key, self.token_until = "", "", 0.0
        self.next_request = 0.0

    def start(self):
        """能力校验结束后开始接受识别请求"""
        self.running = True

    def stop(self):
        """拒绝新调用并等待实际请求结束，再清除令牌"""
        self.stopping.set()
        with self.lock:
            self.running = False
            self.token, self.token_key, self.token_until = "", "", 0.0

    def check(self, cancelled):
        """执行前后同时核对调用者取消及实例停止"""
        if cancelled.is_set() or self.stopping.is_set():
            raise Cancelled("百度 OCR 已取消。")
        if not self.running:
            raise ProviderError("百度 OCR 实例尚未启动。")

    @contextmanager
    def work(self, cancelled):
        """锁等待可取消，停止屏障覆盖完整文件处理及网络执行"""
        while not self.lock.acquire(timeout=0.05):
            self.check(cancelled)
        try:
            self.check(cancelled)
            yield
            self.check(cancelled)
        finally:
            self.lock.release()

    def status(self, _payload=None):
        """只读取本机凭据状态，不发送网络请求或返回密钥"""
        configured = bool(self.config["credentials_file"])
        if configured:
            with self.credentials.borrow(self.reference, PLUGIN_ID, "ocr"):
                pass
        return {"configured": configured, "api": self.config["api"], "running": self.running}

    def access_token(self, cancelled):
        """按当前密钥缓存令牌，文件换钥后不复用旧鉴权"""
        self.check(cancelled)
        with self.credentials.borrow(self.reference, PLUGIN_ID, "ocr") as keys:
            identity = hashlib.sha256(json.dumps(keys, sort_keys=True).encode()).hexdigest()
            if identity == self.token_key and time.monotonic() < self.token_until:
                return self.token
            value = self.transport.post(
                TOKEN_URL,
                {
                    "grant_type": "client_credentials",
                    "client_id": keys["api_key"],
                    "client_secret": keys["secret_key"],
                },
                self.config["request_timeout_seconds"],
            )
        self.check(cancelled)
        token, expires = value.get("access_token"), value.get("expires_in")
        if not isinstance(token, str) or not token or len(token) > 8192:
            raise ProviderError("百度 OCR 鉴权失败，请检查应用密钥和接口权限。")
        if isinstance(expires, bool) or not isinstance(expires, int) or expires <= 0:
            raise ProviderError("百度 OCR 返回了无效的令牌期限。")
        self.token, self.token_key = token, identity
        self.token_until = time.monotonic() + max(0, expires - 60)
        return token

    def connect(self, _payload=None):
        """手动校验鉴权，只请求令牌而不调用计费识别接口"""
        cancelled = threading.Event()
        with self.work(cancelled):
            self.access_token(cancelled)
        return {"connected": True}

    def recognize(self, image, cancelled):
        """上传标准 RGB PNG 并保留提交图像的尺寸坐标"""
        self.check(cancelled)
        if image.width * image.height > MAX_PIXELS:
            raise ProviderError("OCR 图片超过 4000 万像素，请缩小后重试。")
        image = ImageOps.exif_transpose(image).convert("RGB")
        image.thumbnail((self.config["image_long_side"], self.config["image_long_side"]))
        if min(image.size) < 15:
            raise ProviderError("百度 OCR 图片最短边至少需要 15 像素。")
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        fields = {
            "image": base64.b64encode(buffer.getvalue()).decode("ascii"),
            "probability": "true",
            "detect_direction": "false",
        }
        limit_mb = 8 if self.config["api"] == "general" else 10
        if len(urlencode(fields).encode("ascii")) > limit_mb * 1024 * 1024:
            raise ProviderError(f"百度 OCR 请求超过 {limit_mb} MB，请降低识别图片最长边。")
        for attempt in range(2):
            token = self.access_token(cancelled)
            while time.monotonic() < self.next_request:
                self.check(cancelled)
                cancelled.wait(min(0.05, self.next_request - time.monotonic()))
            self.check(cancelled)
            self.next_request = time.monotonic() + self.config["min_request_interval_seconds"]
            value = self.transport.post(
                OCR_URL
                + self.config["api"]
                + "?"
                + urlencode(
                    {
                        "access_token": token,
                    }
                ),
                fields,
                self.config["request_timeout_seconds"],
            )
            self.check(cancelled)
            code = value.get("error_code")
            if code is None:
                break
            if code in (110, 111) and attempt == 0:
                self.token_until = 0.0
                continue
            messages = {
                17: "每日额度已用尽",
                18: "调用频率超过限额",
                19: "总额度已用尽",
                6: "应用没有接口权限",
                216100: "请求参数无效",
                216201: "图片格式无效",
            }
            hint = messages.get(code, "识别失败") if isinstance(code, int) else "返回错误码无效"
            display = str(code) if isinstance(code, int) and not isinstance(code, bool) else "未知"
            raise ProviderError(f"百度 OCR {hint}（错误码 {display}），请检查后重试。")
        return {
            "width": image.width,
            "height": image.height,
            "blocks": convert_blocks(value, image.width, image.height),
            "method": "baidu-" + self.config["api"],
        }

    def pdf_page(self, page, cancelled):
        """可靠文字页本机读取，扫描页和混合页按页发送百度"""
        self.check(cancelled)
        blocks = native_blocks(page) if self.config["native_pdf_text"] else []
        image_area = sum(pymupdf.Rect(item["bbox"]).get_area() for item in page.get_image_info())
        if (
            sum(len(row["text"]) for row in blocks) >= 12
            and image_area <= page.rect.get_area() * 0.15
        ):
            return {
                "width": page.rect.width,
                "height": page.rect.height,
                "blocks": blocks,
                "method": "pdf-text",
            }
        scale = min(
            self.config["pdf_scale"],
            self.config["image_long_side"] / max(page.rect.width, page.rect.height, 1),
        )
        pixels = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
        with Image.open(BytesIO(pixels.tobytes("png"))) as image:
            result = self.recognize(image, cancelled)
        result["blocks"] = blocks + [
            row for row in result["blocks"] if not any(overlaps(row, native) for native in blocks)
        ]
        result["blocks"].sort(key=lambda row: (round(row["box"][1], 2), row["box"][0]))
        return result

    def read_document(self, path, cancelled):
        """返回兼容现有 OCR 的分页文字和比例坐标，取消后不发布结果"""
        started = time.monotonic()
        with self.work(cancelled):
            try:
                path = Path(path)
                if path.stat().st_size > MAX_FILE_BYTES:
                    raise ProviderError("OCR 文件超过 20 MB，请拆分后重试。")
                pages = []
                if path.suffix.lower() == ".pdf":
                    with pymupdf.open(path) as document:
                        if document.needs_pass or not 1 <= len(document) <= MAX_PAGES:
                            raise ProviderError("百度 OCR 支持未加密的 1–12 页 PDF。")
                        for page in document:
                            pages.append(self.pdf_page(page, cancelled))
                            self.check_budget(pages)
                else:
                    with Image.open(path) as image:
                        if getattr(image, "n_frames", 1) != 1:
                            raise ProviderError("多帧图片请拆分或转为 PDF 后识别。")
                        pages.append(self.recognize(image, cancelled))
                    self.check_budget(pages)
            except (OSError, ValueError, RuntimeError, Image.DecompressionBombError):
                raise ProviderError("百度 OCR 无法读取文档，请检查文件。") from None
            self.check(cancelled)
            text = "\n\n".join("\n".join(row["text"] for row in page["blocks"]) for page in pages)
            if not text.strip():
                raise ProviderError("百度 OCR 未识别到文字，请核对图片或手动录入。")
            return {
                "pages": pages,
                "text": text,
                "seconds": round(time.monotonic() - started, 3),
                "needs_review": any(
                    row["confidence"] < REVIEW_SCORE for page in pages for row in page["blocks"]
                ),
                "notice": "扫描页和图片由百度云 OCR 识别；文字和位置需对照原件核对。",
            }

    def check_budget(self, pages):
        """逐页检查累计文字及行数，超限后不继续调用计费接口"""
        blocks = [row for page in pages for row in page["blocks"]]
        if len(blocks) > MAX_BLOCKS or sum(len(row["text"]) for row in blocks) > MAX_TEXT:
            raise ProviderError("OCR 文字超过 10 万字或 6000 行，请拆分文档。")


def activate(context: Context) -> None:
    """通过公开能力和生命周期安装引擎，未配置凭据仍可查看设置"""
    credentials = context.require(ServiceKey("credentials"))
    reference = credentials.register(
        PLUGIN_ID,
        "ocr",
        lambda: load_credentials(
            context.config["credentials_file"],
        ),
    )
    context.effect(lambda: credentials.revoke(reference))
    backend = BaiduOCR(context.config, credentials, reference)
    context.provide(ServiceKey("ocr.backend"), backend.read_document)
    context.lifecycle(backend.start, backend.stop)
    if context.config["credentials_file"]:
        context.health(backend.status)
    context.rpc("status", backend.status)
    context.rpc("connect", backend.connect)
