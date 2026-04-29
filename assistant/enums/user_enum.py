import enum


class UserRole(str, enum.Enum):
    """用户角色枚举"""
    ADMIN = "admin"
    RECRUITER = "recruiter"
    CANDIDATE = "candidate"
