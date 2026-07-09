"""auth_rbac 请求/响应模型(Pydantic v2)。

机密红线:任何响应模型绝不含 password_hash / app_secret*。
统一响应包由 core.response.ok 装配,这里只定义 data 载荷结构。
"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


# ============ 认证 ============
class LoginReq(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=128)


class LoginUser(BaseModel):
    """登录成功后回显的当前用户精简信息。"""

    id: int
    real_name: str
    role: str
    perms: list[str]


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: LoginUser | None = None


class RefreshReq(BaseModel):
    refresh_token: str = Field(..., min_length=1)


# ============ /auth/me ============
class VisibleMp(BaseModel):
    id: int
    mp_name: str
    perm_level: int | None = None


class MeResp(BaseModel):
    id: int
    username: str
    real_name: str
    role: str
    roles: list[str]
    perms: list[str]
    visible_mp: list[VisibleMp]


# ============ 用户管理 ============
class UserItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    real_name: str
    phone: str
    status: int
    roles: list[str]
    created_at: datetime | None = None
    last_login_at: datetime | None = None


class UserPage(BaseModel):
    items: list[UserItem]
    total: int
    page: int
    page_size: int


class UserCreateReq(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    real_name: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=6, max_length=128)
    role_code: str = Field(..., min_length=1, max_length=32)
    phone: str | None = Field(default=None, max_length=20)


class UserCreateResp(BaseModel):
    id: int


class UserUpdateReq(BaseModel):
    real_name: str | None = Field(default=None, max_length=64)
    phone: str | None = Field(default=None, max_length=20)
    status: int | None = Field(default=None, ge=0, le=1)


class UserRolesReq(BaseModel):
    role_codes: list[str] = Field(..., min_length=1)


class UserPasswordReq(BaseModel):
    new_password: str = Field(..., min_length=6, max_length=128)


class UserMpItem(BaseModel):
    mp_account_id: int
    mp_name: str
    perm_level: int
    assigned_at: datetime | None = None


# ============ 角色 ============
class RoleItem(BaseModel):
    role_code: str
    role_name: str
    perms: list[str]


# ============ 审计查询 ============
class AuditItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    biz_type: str
    biz_id: int
    action: str
    from_status: str
    to_status: str
    auditor_id: int | None = None
    opinion: str
    created_at: datetime | None = None


class AuditPage(BaseModel):
    items: list[AuditItem]
    total: int
    page: int
    page_size: int
