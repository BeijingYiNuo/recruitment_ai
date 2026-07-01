"""
微信公众平台 API 路由 - 消息验证码登录
===================================
个人订阅号通过消息触发验证码实现登录。
保留原有账号密码登录方式，新增微信作为登录方式之一。
"""

import hashlib
import random
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from assistant.config.database import get_db
from assistant.entity import User
from assistant.enums import UserRole
from assistant.user_management.auth_utils import create_access_token
from assistant.user_management.auth_middleware import get_current_user_id
from assistant.utils.logger import logger

# ============================================================
# 微信配置（请根据实际情况修改）
# ============================================================
WECHAT_TOKEN = "yinuo_wechat_2024"       # 微信公众号后台配置的 Token
APP_ID = "wx246eca7b4852c85b"            # 你的 AppID
APP_SECRET = "2ffc9c9ac07250d8ef9da7a8027e0855"  # 你的 AppSecret

# ============================================================
# 验证码存储（内存，服务重启丢失。生产环境建议改用 Redis）
# ============================================================
# verify_codes[code] = {"openid": str, "created_at": datetime}
verify_codes: Dict[str, Dict] = {}
CODE_EXPIRE_MINUTES = 5


# ============================================================
# Pydantic 请求/响应模型
# ============================================================
class VerifyCodeRequest(BaseModel):
    """验证码校验请求"""
    code: str = Field(..., min_length=6, max_length=6, description="6位验证码")


class BindRequest(BaseModel):
    """微信 OpenID 绑定请求"""
    openid: str = Field(..., min_length=1, description="微信 OpenID")


class WeChatLoginResponse(BaseModel):
    """微信登录响应"""
    access_token: str
    token_type: str = "Bearer"
    user_id: int
    username: str
    email: str = ""
    is_new_user: bool = False


router = APIRouter(prefix="/api/wechat", tags=["微信登录"])


# ============================================================
# 内部工具函数
# ============================================================

def _check_signature(token: str, signature: str, timestamp: str, nonce: str) -> bool:
    """校验微信服务器签名"""
    tmp_list = [token, timestamp, nonce]
    tmp_list.sort()
    tmp_str = "".join(tmp_list)
    return hashlib.sha1(tmp_str.encode()).hexdigest() == signature


def _parse_xml(xml_data: bytes) -> Dict[str, str]:
    """解析微信推送的 XML 消息"""
    root = ET.fromstring(xml_data)
    return {child.tag: child.text or "" for child in root}


def _build_text_reply(to_user: str, from_user: str, content: str) -> str:
    """构造文本回复 XML"""
    timestamp = int(time.time())
    return f"""<xml>
<ToUserName><![CDATA[{to_user}]]></ToUserName>
<FromUserName><![CDATA[{from_user}]]></FromUserName>
<CreateTime>{timestamp}</CreateTime>
<MsgType><![CDATA[text]]></MsgType>
<Content><![CDATA[{content}]]></Content>
</xml>"""


def _generate_code() -> str:
    """生成 6 位数字验证码"""
    return f"{random.randint(0, 999999):06d}"


def _cleanup_expired_codes():
    """清理过期验证码"""
    now = datetime.utcnow()
    expired = [
        code for code, data in verify_codes.items()
        if now - data["created_at"] > timedelta(minutes=CODE_EXPIRE_MINUTES)
    ]
    for code in expired:
        del verify_codes[code]
    if expired:
        logger.info(f"微信验证码清理：已过期 {len(expired)} 个")


def _find_or_create_wechat_user(db: Session, openid: str) -> tuple[User, bool]:
    """
    根据 OpenID 查找或创建用户。
    返回 (user, is_new_user)
    """
    user = db.query(User).filter(User.wechat_openid == openid).first()
    if user:
        return user, False

    # 创建新用户（用户名取 openid 后 8 位）
    short_id = openid[-8:] if len(openid) >= 8 else openid
    username = f"wx_{short_id}"
    # 如果用户名已存在，加随机后缀
    while db.query(User).filter(User.username == username).first():
        suffix = random.randint(100, 999)
        username = f"wx_{short_id}_{suffix}"

    user = User(
        username=username,
        email=f"{username}@wechat.local",
        phone="",
        password_hash="",  # 微信用户无密码
        role=UserRole.CANDIDATE,
        status="ACTIVE",
        wechat_openid=openid,
        recruiter_id=0,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    logger.info(f"微信新用户创建: id={user.id}, openid={openid[:10]}...")
    return user, True


# ============================================================
# API 接口
# ============================================================

@router.get("/callback")
def wechat_verify(
    signature: str = "",
    timestamp: str = "",
    nonce: str = "",
    echostr: str = "",
):
    """
    微信服务器 URL 验证接口（GET）
    微信公众号后台配置 URL 时，微信会发 GET 请求验证。
    校验签名通过后返回 echostr 即可验证成功。
    """
    if _check_signature(WECHAT_TOKEN, signature, timestamp, nonce):
        logger.info("微信 URL 验证通过")
        return Response(content=echostr, media_type="text/plain")
    logger.warning(f"微信 URL 验证失败: signature={signature}")
    raise HTTPException(status_code=403, detail="签名验证失败")


@router.post("/callback")
async def wechat_callback(request: Request):
    """
    接收微信用户消息（POST）
    微信服务器将用户发送的消息以 XML 格式推送至此接口。
    根据消息内容处理验证码逻辑并被动回复。
    """
    raw_body = await request.body()
    try:
        msg = _parse_xml(raw_body)
    except ET.ParseError as e:
        logger.error(f"微信消息 XML 解析失败: {e}")
        return Response(content="success", media_type="text/plain")

    from_user = msg.get("FromUserName", "")       # 用户 OpenID
    to_user = msg.get("ToUserName", "")            # 公众号 AppID
    msg_type = msg.get("MsgType", "")              # 消息类型
    content = msg.get("Content", "").strip()       # 消息内容
    msg_id = msg.get("MsgId", "")                  # 消息 ID（可用于去重）

    logger.info(f"收到微信消息: from={from_user[:10]}..., type={msg_type}, content={content[:20]}")

    # 仅处理文本消息
    if msg_type != "text":
        reply = _build_text_reply(from_user, to_user, "暂不支持此类型消息，请发送文字「登录」获取验证码")
        return Response(content=reply, media_type="application/xml")

    # --- 消息是 "登录" 或 "login" → 生成验证码 ---
    if content.lower() in ("登录", "login", "登陆"):
        _cleanup_expired_codes()
        code = _generate_code()
        # 确保验证码不重复
        while code in verify_codes:
            code = _generate_code()
        verify_codes[code] = {
            "openid": from_user,
            "created_at": datetime.utcnow(),
        }
        logger.info(f"生成验证码: code={code}, openid={from_user[:10]}...")
        reply_text = (
            f"✓ 您的验证码是：{code}\n"
            f"请在 {CODE_EXPIRE_MINUTES} 分钟内登录网页时输入。"
            f"如非本人操作请忽略。"
        )
        reply = _build_text_reply(from_user, to_user, reply_text)
        return Response(content=reply, media_type="application/xml")

    # --- 消息是 6 位数字 → 尝试匹配验证码 ---
    if content.isdigit() and len(content) == 6:
        _cleanup_expired_codes()
        code_data = verify_codes.get(content)
        if code_data and code_data["openid"] == from_user:
            reply_text = "✓ 验证码有效，请回到网页完成登录。"
            logger.info(f"微信端验证码匹配成功: code={content}, openid={from_user[:10]}...")
        elif code_data and code_data["openid"] != from_user:
            reply_text = "✗ 验证码不属于当前账号，请发送「登录」获取新验证码。"
        else:
            reply_text = "✗ 验证码无效或已过期，请发送「登录」获取新验证码。"
        reply = _build_text_reply(from_user, to_user, reply_text)
        return Response(content=reply, media_type="application/xml")

    # --- 其他消息 → 提示 ---
    reply = _build_text_reply(
        from_user, to_user,
        "回复「登录」获取网页登录验证码。"
    )
    return Response(content=reply, media_type="application/xml")


@router.post("/verify_code", response_model=WeChatLoginResponse)
def verify_code(
    req: VerifyCodeRequest,
    db: Session = Depends(get_db),
):
    """
    网页提交验证码 → 校验 → 签发 JWT
    如果该 OpenID 尚未绑定用户，自动创建新用户。
    """
    _cleanup_expired_codes()
    code = req.code.strip()

    code_data = verify_codes.get(code)
    if not code_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="验证码无效或已过期",
        )

    openid = code_data["openid"]

    # 删除已使用的验证码（先删再处理，避免重复使用）
    del verify_codes[code]

    # 查找或创建用户
    try:
        user, is_new = _find_or_create_wechat_user(db, openid)
    except Exception as e:
        logger.error(f"微信登录创建用户失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="登录失败，请稍后重试",
        )

    # 更新最后登录时间
    user.last_login_at = datetime.now()
    db.commit()

    # 签发 JWT
    access_token = create_access_token(data={"sub": str(user.id)})

    logger.info(f"微信登录成功: user_id={user.id}, is_new={is_new}, openid={openid[:10]}...")

    return WeChatLoginResponse(
        access_token=access_token,
        token_type="Bearer",
        user_id=user.id,
        username=user.username,
        email=user.email or "",
        is_new_user=is_new,
    )


@router.post("/bind")
def bind_wechat(
    req: BindRequest,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):
    """
    将微信 OpenID 绑定到当前登录的账号。
    登录后用户在个人中心主动绑定。
    """
    openid = req.openid.strip()

    # 检查该 OpenID 是否已被其他用户绑定
    existing = db.query(User).filter(User.wechat_openid == openid).first()
    if existing:
        if existing.id == current_user_id:
            return {"success": True, "message": "该微信已绑定到当前账号"}
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="该微信账号已被其他用户绑定",
        )

    # 绑定到当前用户
    user = db.query(User).filter(User.id == current_user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在",
        )

    user.wechat_openid = openid
    db.commit()

    logger.info(f"微信绑定成功: user_id={current_user_id}, openid={openid[:10]}...")
    return {"success": True, "message": "微信账号绑定成功"}
