"""管理独立日志库的采集配置，不记录配置操作自身"""

from contextlib import closing

from resume_maker.domain.activity import ACTIVITY_CATEGORIES, ActivityCaptureSettings
from resume_maker.infrastructure.activity import ActivityLog
from resume_maker.sdk.records import dump


def capture_settings(log: ActivityLog) -> ActivityCaptureSettings:
    """读取当前实例实际使用的采集类别"""
    with log.lock:
        return ActivityCaptureSettings(
            categories=[
                category for category in ACTIVITY_CATEGORIES if category in log.capture_categories
            ],
            capture_starts=log.capture_starts,
        )


def save_capture_settings(log: ActivityLog, settings: ActivityCaptureSettings):
    """配置提交成功后同步切换写入策略，失败时保留原策略"""
    with log.lock, closing(log.connect()) as conn:
        conn.executemany(
            "INSERT INTO metadata(key,value) VALUES (?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            [
                ("capture_categories", dump(settings.categories)),
                ("capture_starts", dump(settings.capture_starts)),
            ],
        )
        conn.commit()
        log.capture_categories = frozenset(settings.categories)
        log.capture_starts = settings.capture_starts
    return settings
