import enum


class PositionStatus(str, enum.Enum):
    """岗位状态枚举"""
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class RoundType(str, enum.Enum):
    """面试轮次类型枚举"""
    TECHNICAL = "TECHNICAL"      # 技术面
    HR = "HR"                    # HR面
    MANAGER = "MANAGER"          # 主管面
    BEHAVIORAL = "BEHAVIORAL"    # 行为面
    WRITTEN = "WRITTEN"          # 笔试
    GROUP = "GROUP"              # 群面
