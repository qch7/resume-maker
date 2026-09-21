"""显式授权后，用 CC Switch 中指定供应商评测模板，配置、会话和产物完全隔离。

密钥只传入 CLI 子进程环境，不保存到报告、命令行或测试配置。
正式 SQLite 数据库以只读方式打开，模型不共享会话或映射缓存
"""

import argparse
import hashlib
import json
import sqlite3
import threading
import time
import tomllib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pymupdf

from resume_maker.domain.honor_entries import sync_honor_document
from resume_maker.domain.models import ProviderSettings
from resume_maker.domain.resume import ResumeDocument
from resume_maker.integrations.providers.base import StructuredOutputError
from resume_maker.integrations.providers.codex import CodexProvider
from resume_maker.integrations.word.recovery import prepare_template
from resume_maker.integrations.word.rendering import render_word
from resume_maker.integrations.word.templates.fill import fill_template
from resume_maker.integrations.word.templates.mapping import TemplatePackage
from resume_maker.integrations.word.templates.values import personal_values, section_records
from resume_maker.services.templates.analysis import analyze_plan


def save(path, value):
    """保存不含供应商认证的评测数据"""
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def readonly(path):
    """以 SQLite 只读连接保护正式数据库"""
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)


def profile(path, resume_id):
    """取得当前简历、固定项目版本及同步荣誉的只读快照"""
    with readonly(path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM resumes WHERE document_json IS NOT NULL "
            "AND (? = '' OR id = ?) AND id NOT IN (SELECT resume_id FROM resume_deletions) "
            "ORDER BY updated_at DESC LIMIT 1",
            (resume_id, resume_id),
        ).fetchone()
        if row is None:
            raise ValueError("没有可供试填的简历资料。")
        honors = [
            json.loads(r[0])
            for r in conn.execute("SELECT value_json FROM settings WHERE key LIKE 'honor:%'")
        ]
        document = ResumeDocument.model_validate(
            sync_honor_document(json.loads(row["document_json"]), honors)
        )
        projects = []
        for item in json.loads(row["items_json"]):
            revision = conn.execute(
                "SELECT content_json FROM revisions WHERE id=?", (item["revision_id"],)
            ).fetchone()
            projects.append({**item, "content": json.loads(revision[0])})
    return document, projects


def isolated_provider(database, name, directory):
    """从 CC Switch 只读提取指定供应商配置"""
    with readonly(database) as conn:
        rows = conn.execute(
            "SELECT settings_config FROM providers WHERE app_type='codex' AND name=?", (name,)
        ).fetchall()
    if len(rows) != 1:
        raise ValueError(f"供应商名称须唯一：{name}")
    stored = json.loads(rows[0][0])
    config = tomllib.loads(stored["config"])
    upstream = config["model_providers"][config["model_provider"]]
    key = stored.get("auth", {}).get("OPENAI_API_KEY")
    if not key:
        raise ValueError(f"供应商没有 API Key：{name}")
    home = directory / "codex-home"
    home.mkdir(parents=True, exist_ok=True)
    model = config["model"]
    settings = ProviderSettings(
        model=model,
        reasoning_effort=config.get("model_reasoning_effort", ""),
        timeout_seconds=600,
    )
    # JSON 字符串的引号和转义可用于此处的 TOML 基本字符串，不经过 shell
    quote = json.dumps
    lines = [
        'model_provider = "evaluation"',
        f"model = {quote(model)}",
        'approval_policy = "never"',
        'sandbox_mode = "read-only"',
        'web_search = "disabled"',
        "disable_response_storage = true",
    ]
    catalog_source = Path(config.get("model_catalog_json", ""))
    if not catalog_source.is_absolute():
        catalog_source = Path.home() / ".codex" / catalog_source
    if config.get("model_catalog_json") and catalog_source.is_file():
        catalog = home / "models.json"
        # CLI 读取根据 modelCatalog 表单生成的完整模型目录
        save(catalog, json.loads(catalog_source.read_text(encoding="utf-8")))
        lines.append(f"model_catalog_json = {quote(str(catalog))}")
    lines.extend(
        [
            "[model_providers.evaluation]",
            f"name = {quote(name)}",
            f"base_url = {quote(upstream['base_url'])}",
            f"wire_api = {quote(upstream.get('wire_api', 'responses'))}",
            'env_key = "RESUME_EVALUATION_API_KEY"',
            "requires_openai_auth = false",
        ]
    )
    (home / "config.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"CODEX_HOME": str(home), "RESUME_EVALUATION_API_KEY": key}, settings


class RecordedProvider(CodexProvider):
    """记录实际发给模型的证据和原始映射，便于区分模型错误和程序补全"""

    def __init__(self, environment, directory):
        """配置仅属于本次模型和模板的独立会话目录"""
        super().__init__(environment=environment)
        self.directory, self.calls = directory, 0

    def run_structured(self, **kwargs):
        """保存每轮输入输出并通过同一生产 Provider 调用模型"""
        self.calls += 1
        number = self.calls
        snapshot = kwargs["workspace"] / "original.docx"
        if snapshot.exists():
            (self.directory / f"request-{number}-source.docx").write_bytes(snapshot.read_bytes())
        (self.directory / f"request-{number}.txt").write_text(kwargs["prompt"], encoding="utf-8")
        save(
            self.directory / f"request-{number}-metadata.json",
            {
                "model": kwargs["settings"].model,
                "resumed": bool(kwargs.get("thread_id")),
                "images": [str(path) for path in kwargs.get("images", [])],
            },
        )
        try:
            result = super().run_structured(**kwargs)
        except StructuredOutputError as exc:
            save(
                self.directory / f"response-{number}-invalid.json",
                {"response": exc.response, "issues": exc.issues},
            )
            raise
        save(self.directory / f"response-{number}.json", result.model_dump())
        return result


def normalized(text):
    """去除排版换行和空格以核验真实文本"""
    return "".join(text.split())


def inspect_output(pdf, document, projects):
    """独立检查试填内容并记录页码、姓名和栏目位置"""
    with pymupdf.open(pdf) as rendered:
        # 原生浮动标题可能最后写入 PDF 内容流，跨页正文须同时按页面阅读顺序检查
        combined = [
            normalized("\n".join(page.get_text(sort=sort) for page in rendered))
            for sort in (False, True)
        ]
        values = [
            value
            for key, value in personal_values(document).items()
            if key.startswith("personal.") and key != "personal.photo" and value
        ]
        sections = []
        for section in document.sections:
            records = section_records(document, section.title, projects)
            if not records:
                continue
            sections.append(section.title)
            for record in records:
                for key in (
                    "title",
                    "subtitle",
                    "period",
                    "role",
                    "stack",
                    "description",
                    "details",
                    "highlights",
                    "custom_fields",
                ):
                    # details 包含可变标签，因此按原始字段分别检查内容
                    if section.kind == "projects" and key == "details":
                        continue
                    value = record.get(key)
                    if isinstance(value, str):
                        values.extend(line for line in value.splitlines() if line.strip())
        missing = sorted(
            {value for value in values if not any(normalized(value) in text for text in combined)}
        )
        name = document.personal.name
        name_hits = (
            [
                {"page": i + 1, "rect": list(rect)}
                for i, page in enumerate(rendered)
                for rect in page.search_for(name)
            ]
            if name
            else []
        )
        return {
            "pages": len(rendered),
            "missing_values": missing,
            "missing_headings": [
                title
                for title in sections
                if not any(normalized(title) in text for text in combined)
            ],
            "name_positions": name_hits,
            "name_on_first_page": not name or any(hit["page"] == 1 for hit in name_hits),
            "placeholder_remaining": any(
                marker in text for text in combined for marker in ("〔自动条目占位〕", "〔待填写〕")
            ),
        }


def inspect_record_counts(path, document, projects):
    """按资料允许的总出现次数检查记录标识，不同条目共用同一值不属于多填"""
    values = [
        value
        for key, value in personal_values(document).items()
        if key.startswith("personal.") and key != "personal.photo" and value
    ]
    anchors = set()
    for section in document.sections:
        records = section_records(document, section.title, projects)
        if records:
            values.append(section.title)
        for record in records:
            identity = record.get("title") or record.get("details")
            if identity:
                anchors.add(identity)
            for key in (
                "title",
                "subtitle",
                "period",
                "role",
                "stack",
                "description",
                "details",
                "highlights",
                "custom_fields",
            ):
                if key == "details" and section.kind == "projects":
                    continue
                value = record.get(key)
                if isinstance(value, str) and value:
                    values.append(value)
    package = TemplatePackage(path)
    actual = normalized(
        "\n".join(row["text"] for row in package.inventory()["nodes"] if row["kind"] == "p")
    )
    expected = normalized("\n".join(values))
    counts = [
        {
            "identity": value,
            "expected": expected.count(normalized(value)),
            "actual": actual.count(normalized(value)),
        }
        for value in sorted(anchors)
    ]
    return {
        "counts": counts,
        "duplicates": [row for row in counts if row["actual"] > row["expected"]],
    }


def accepted_output(report):
    """只有实际渲染并通过独立内容检查的映射才算成功，ready 本身不足以验收"""
    check = report.get("content_check", {})
    return bool(
        report.get("ready")
        and not report.get("error")
        and not report.get("render_error")
        and check.get("pages", 0) > 0
        and check.get("name_on_first_page")
        and not check.get("missing_values")
        and not check.get("missing_headings")
        and not check.get("placeholder_remaining")
        and not report.get("record_count_check", {}).get("duplicates")
    )


def evaluate(args, supplier, source, document, projects):
    """完成单份模板的真实识别、生成、渲染和独立内容检查"""
    directory = args.output / supplier / source.stem
    directory.mkdir(parents=True, exist_ok=False)
    environment, settings = isolated_provider(args.cc_switch_db, supplier, directory)
    provider = RecordedProvider(environment, directory)
    events, flag = [], threading.Event()
    original_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    started = time.monotonic()

    def emit(kind, data):
        """仅记录公开事件"""
        if kind in {"activity", "metrics", "usage", "thread"}:
            events.append(
                {"kind": kind, "data": data, "seconds": round(time.monotonic() - started, 2)}
            )
            save(directory / "events.json", events)
        if kind == "activity":
            print(
                json.dumps(
                    {
                        "provider": supplier,
                        "template": source.name,
                        "activity": data.get("text", ""),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )

    report = {"provider": supplier, "model": settings.model, "template": source.name}
    try:
        snapshot = directory / "original.docx"
        package, notices = prepare_template(
            source, snapshot, provider, settings, flag, emit, document, projects
        )
        plan, review, attempts, error = analyze_plan(
            package, provider, directory, document, projects, settings, flag, emit
        )
        save(directory / "plan.json", plan.model_dump())
        save(directory / "review.json", review)
        report.update(
            ready=review["ready"],
            attempts=attempts,
            repair_error=error,
            preparation_notices=notices,
        )
        if review["ready"]:
            output = directory / "resume.docx"
            fill_template(snapshot, output, plan, document.model_dump(), projects)
            report["record_count_check"] = inspect_record_counts(output, document, projects)
            pages, error = render_word(output, directory / "resume.pdf")
            report.update(pages=pages, render_error=error)
            if not error:
                report["content_check"] = inspect_output(
                    directory / "resume.pdf", document, projects
                )
    except Exception as exc:
        # 不记录进程环境、配置或请求头，异常可能含认证值时替换后再落盘
        report["error"] = str(exc).replace(environment["RESUME_EVALUATION_API_KEY"], "[redacted]")
    report.update(
        seconds=round(time.monotonic() - started, 2),
        calls=provider.calls,
        source_unchanged=hashlib.sha256(source.read_bytes()).hexdigest() == original_hash,
    )
    report["passed"] = accepted_output(report) and report["source_unchanged"]
    save(directory / "report.json", report)
    print(json.dumps(report, ensure_ascii=False), flush=True)
    return report


def main():
    """显式指定输入、供应商和产物目录后启动评测矩阵"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc-switch-db", type=Path, required=True)
    parser.add_argument("--data-db", type=Path, required=True)
    parser.add_argument("--resume-id", default="")
    parser.add_argument("--templates", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--providers", nargs="+", required=True)
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    document, projects = profile(args.data_db, args.resume_id)
    sources = (
        [args.templates]
        if args.templates.is_file()
        else sorted(
            path for path in args.templates.iterdir() if path.suffix.lower() in {".docx", ".pdf"}
        )
    )
    if not sources:
        parser.error("模板目录中没有 DOCX 或 PDF 文件。")
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        jobs = [
            pool.submit(evaluate, args, supplier, source, document, projects)
            for source in sources
            for supplier in args.providers
        ]
        reports = [job.result() for job in jobs]
    save(args.output / "report.json", reports)
    if not all(report["passed"] for report in reports):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
