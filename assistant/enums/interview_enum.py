import enum


class SessionType(str, enum.Enum):
    """面试类型枚举"""
    ONLINE = "online"
    OFFLINE = "offline"


class SessionStatus(str, enum.Enum):
    """面试状态枚举"""
    SCHEDULED = "scheduled"
    ONGOING = "ongoing"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    PASSED = "passed"
    FAILED = "failed"
    PENDING = "pending"


class Recommendation(str, enum.Enum):
    """推荐意见枚举"""
    RECOMMEND = "recommend"
    NOT_RECOMMEND = "not_recommend"
    NEUTRAL = "neutral"


class ReminderStatus(str, enum.Enum):
    """提醒状态枚举"""
    PENDING = "pending"
    SENT = "sent"
    DELIVERED = "delivered"
    READ = "read"


class SendMethod(str, enum.Enum):
    """发送方式枚举"""
    SMS = "sms"
    EMAIL = "email"
    SYSTEM = "system"


class ReportStatus(str, enum.Enum):
    """报告状态枚举"""
    GENERATING = "generating"   # 生成中
    FINAL = "final"             # 已完成
    FAILED = "failed"           # 生成失败


class QuestionType(str, enum.Enum):
    """问题类型枚举"""
    TECHNICAL = "technical"
    BEHAVIORAL = "behavioral"
    SITUATIONAL = "situational"


class RoundStatus(str, enum.Enum):
    """面试轮次状态枚举"""
    PENDING = "pending"        # 待面试
    PASS = "pass"              # 通过
    FAIL = "fail"              # 未通过
    SKIP = "skip"              # 跳过
