import enum


class ResumeStatus(str, enum.Enum):
    """简历状态枚举"""
    UPLOADED = "UPLOADED"
    PROCESSED = "PROCESSED"
    ANALYZED = "ANALYZED"
    FAILED_ANALYSIS = "FAILED_ANALYSIS"


class ReviewDecision(str, enum.Enum):
    """简历审核决策枚举"""
    PASS = "PASS"       # 通过
    PENDING = "PENDING" # 待定
    FAIL = "FAIL"       # 淘汰
