import enum


class ResumeStatus(str, enum.Enum):
    """简历状态枚举"""
    UPLOADED = "UPLOADED"
    PROCESSED = "PROCESSED"
    ANALYZED = "ANALYZED"
    FAILED_ANALYSIS = "FAILED_ANALYSIS"
