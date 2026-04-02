import enum


class ResumeStatus(str, enum.Enum):
    """简历状态枚举"""
    UPLOADED = "uploaded"
    UNANALYZED = "unanalyzed"
    ANALYZED = "analyzed"
