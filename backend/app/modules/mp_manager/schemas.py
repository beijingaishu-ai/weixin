"""mp_manager 出入参模型(Pydantic v2)。

机密红线:任何出参模型都不得包含 app_secret / app_secret_cipher。
台账/详情仅回显 app_secret_masked 固定占位 "****"(我们不持明文,也不解密回显)。
account_type / status / perm_level 等均用 int。
"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# 出参:台账 / 详情(零 secret)
# ---------------------------------------------------------------------------
class MpAccountItem(BaseModel):
    """台账列表项 / 详情公共字段。绝不含任何 secret。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    mp_name: str
    wx_original_id: str
    app_id: str
    account_type: int
    is_verified: int
    need_review: int
    ip_whitelist_ok: int
    status: int
    last_verified_at: datetime | None = None
    # 浏览器发布登录态授权(仅真实号 account_type∈{1,2} 有意义;前端对 type=3 展示 Mock)
    wx_login_status: str = "UNAUTHORIZED"
    wx_login_expires_at: datetime | None = None
    remark: str
    created_at: datetime | None = None
    # 固定占位:系统不持有明文,故不做真实 mask,仅显示 "****"
    app_secret_masked: str = "****"


class AssigneeItem(BaseModel):
    """公众号运营分配项。"""

    user_id: int
    real_name: str
    perm_level: int
    assigned_at: datetime | None = None


class MpAccountDetail(MpAccountItem):
    """详情:台账字段 + 分配人清单。"""

    assignees: list[AssigneeItem] = Field(default_factory=list)


class MpAccountPage(BaseModel):
    """分页台账。"""

    items: list[MpAccountItem]
    total: int
    page: int
    page_size: int


# ---------------------------------------------------------------------------
# 入参:创建 / 更新
# ---------------------------------------------------------------------------
class MpAccountCreate(BaseModel):
    mp_name: str = Field(..., min_length=1, max_length=64)
    account_type: int = Field(..., ge=1, le=3, description="1=订阅号 2=服务号 3=测试/模拟号")
    app_id: str = Field(..., min_length=1, max_length=32)
    app_secret: str = Field(..., min_length=1, max_length=128)
    wx_original_id: str = Field("", max_length=32)
    is_verified: int = Field(0, ge=0, le=1)
    remark: str = Field("", max_length=255)


class MpAccountUpdate(BaseModel):
    mp_name: str | None = Field(None, min_length=1, max_length=64)
    app_secret: str | None = Field(None, min_length=1, max_length=128)
    status: int | None = Field(None, description="1=正常 2=凭据异常 0=停用")
    need_review: int | None = Field(None, ge=0, le=1)
    remark: str | None = Field(None, max_length=255)
    is_verified: int | None = Field(None, ge=0, le=1)


# ---------------------------------------------------------------------------
# 出参:创建结果 / 校验结果
# ---------------------------------------------------------------------------
class MpCreateResult(BaseModel):
    id: int


class VerifyResult(BaseModel):
    ok: bool
    checked: str
    hint: str


# ---------------------------------------------------------------------------
# 运营分配:全量覆盖式入参 / diff 出参
# ---------------------------------------------------------------------------
class AssignmentIn(BaseModel):
    user_id: int
    perm_level: int = Field(..., ge=1, le=4, description="1=只读 2=编辑 3=提审 4=发布")


class AssigneesUpdate(BaseModel):
    assignments: list[AssignmentIn] = Field(default_factory=list)


class AssignDiff(BaseModel):
    added: list[int] = Field(default_factory=list)
    removed: list[int] = Field(default_factory=list)
    changed: list[int] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 内部凭据接口(仅 wx-gateway 内网调用;含明文 secret,故独立于所有出参红线之外)
# ---------------------------------------------------------------------------
class CredentialOut(BaseModel):
    app_id: str
    app_secret: str
