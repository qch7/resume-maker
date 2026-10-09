"""招聘收藏夹的本机存储、并发保存和原子导入"""

from pydantic import ValidationError

from resume_maker.core.errors import Problem
from resume_maker.domain.recruitment import RecruitmentFile, empty_recruitment, merge_recruitment
from resume_maker.infrastructure.database import Database, dump, unpack

KEY = "recruitment-bookmarks"


def parse_recruitment(content: str) -> RecruitmentFile:
    """校验完整交换文件，将字段位置转换为可直接显示的错误"""
    if len(content.encode("utf-8")) > 8_000_000:
        raise Problem("导入文件超过 8 MB。", 413)
    try:
        return RecruitmentFile.model_validate_json(content.lstrip("\ufeff"))
    except ValidationError as error:
        details = [
            f"{'.'.join(map(str, item['loc'])) or '文件'}：{item['msg']}"
            for item in error.errors(include_input=False, include_url=False)[:5]
        ]
        raise Problem("文件格式不正确：\n" + "\n".join(details), 422) from error


class Recruitment:
    """使用现有设置表保存收藏夹，随业务数据库备份和恢复"""

    def __init__(self, db: Database):
        """持有当前实例的数据库，不连接外部招聘网站"""
        self.db = db

    def get(self):
        """首次访问返回空收藏夹，企业清单由用户主动导入"""
        return self.db.setting(KEY, {"revision": 0, "data": empty_recruitment().model_dump()})

    def _current(self, conn, revision):
        """在事务中核验最新版本，拒绝旧窗口或过期导入预览覆盖数据"""
        row = unpack(conn.execute("SELECT value_json FROM settings WHERE key=?", (KEY,)).fetchone())
        current = row["value"] if row else {"revision": 0, "data": empty_recruitment().model_dump()}
        if revision != current["revision"]:
            raise Problem("收藏夹已在其他窗口修改，请刷新后重试；当前编辑内容仍保留。", 409)
        return current

    def _write(self, conn, current, data: RecruitmentFile):
        """完整数据校验后一次写入，重复保存保持版本不变"""
        value = data.model_dump()
        if value == current["data"]:
            return current
        saved = {"revision": current["revision"] + 1, "data": value}
        conn.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (KEY, dump(saved)))
        return saved

    def save(self, revision: int, data: RecruitmentFile):
        """保存用户编辑后的完整收藏夹，版本核验和写入处于同一事务"""
        with self.db.transaction() as conn:
            return self._write(conn, self._current(conn, revision), data)

    def import_file(self, revision: int, content: str, policy, *, preview: bool):
        """预览只计算变化，确认导入时重新校验版本并原子合并"""
        incoming = parse_recruitment(content)
        with self.db.transaction() as conn:
            current = self._current(conn, revision)
            try:
                merged, summary = merge_recruitment(
                    RecruitmentFile.model_validate(current["data"]), incoming, policy
                )
            except ValidationError as error:
                raise Problem("合并后超过收藏夹容量，请减少条目后再导入。", 422) from error
            if preview:
                return {"revision": current["revision"], **summary}
            saved = self._write(conn, current, merged)
            return {"snapshot": saved, "summary": summary}
