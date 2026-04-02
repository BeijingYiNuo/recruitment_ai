import enum


class UserRole(str, enum.Enum):
    """用户角色枚举"""
    ADMIN = "admin"
    RECRUITER = "recruiter"
    CANDIDATE = "candidate"


class UserStatus(str, enum.Enum):
    """用户状态枚举"""
    ACTIVATE = "activate"
    INACTIVATE = "inactivate"
    DELETED = "deleted"
