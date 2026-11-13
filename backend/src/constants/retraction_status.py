"""Customer retraction lifecycle — shared with frontend/src/constants/retractionStatus.ts."""
from enum import StrEnum


class RetractionStatus(StrEnum):
    PENDING = "pending"      # 待确认：影响清单已生成，尚未隐藏任何字段
    CONFIRMED = "confirmed"  # 已生效：个人字段已在当前维度 / 回溯 / 导出中隐藏
    FAILED = "failed"        # 撤回失败：已回滚到上一可用版本，可重试


RETRACTION_STATUS_LABELS: dict[str, str] = {
    "pending": "待确认",
    "confirmed": "已生效",
    "failed": "撤回失败",
}
