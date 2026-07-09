"""统一发文状态机(对齐设计第 2 章 2.3.3 与附录 A.2)。

作为 content-center 与 publish-engine 的共享事实源:任何状态迁移必须经 can_transition 校验。
M1/M2 覆盖 content_article 段与 publish_task 段;collect_article 段(COLLECTED/UNMATCHED/
MAPPED)在 M3 采集/映射阶段启用。
"""
from enum import StrEnum


class CollectStatus(StrEnum):
    """collect_article.status 段(M3 采集/映射)。"""

    COLLECTED = "COLLECTED"      # 采集入库,待映射
    MAPPED = "MAPPED"            # 已命中映射规则(≥1 目标号)
    TRANSFORMED = "TRANSFORMED"  # 已转换产出 content_article(交接点)
    UNMATCHED = "UNMATCHED"      # 无规则命中 / 去重命中 / 原创未授权拦截(终态,可人工复盘再跑)


class ArticleStatus(StrEnum):
    """content_article.status 段。"""

    TRANSFORMED = "TRANSFORMED"        # 已编排/转换完成,待提审(人工稿初始态,也用于采集转换产物)
    PENDING_REVIEW = "PENDING_REVIEW"  # 已提审,待审核
    APPROVED = "APPROVED"              # 审核通过(或双层开关关闭时自动过审)
    REJECTED = "REJECTED"              # 审核驳回
    DRAFT_CREATED = "DRAFT_CREATED"    # 已建微信草稿(draft_media_id 回写本表)


class TaskStatus(StrEnum):
    """publish_task.status 段。"""

    SCHEDULED = "SCHEDULED"
    PUBLISHING = "PUBLISHING"
    PUBLISHED = "PUBLISHED"
    FAILED = "FAILED"


class GroupStatus(StrEnum):
    """content_draft_group.status —— 组局部状态,不属于统一发文状态机。"""

    EDITING = "EDITING"
    READY = "READY"
    PUBLISHED = "PUBLISHED"


class WxLoginStatus(StrEnum):
    """mp_account.wx_login_status —— 浏览器发布登录态(扫码授权)状态,独立于 TaskStatus。

    详见 docs/浏览器发布登录态授权设计.md。扫码后 now < expires_at 即窗口内可全自动发布。
    """

    UNAUTHORIZED = "UNAUTHORIZED"  # 从未扫码 / storage_state 文件缺失(初始态)
    AUTHORIZED = "AUTHORIZED"      # 扫码成功且 now < expires_at,可全自动发布
    EXPIRING = "EXPIRING"          # now >= expires_at - WARN_HOURS 且仍 < expires_at(仍可发,已告警续扫)
    EXPIRED = "EXPIRED"            # now >= expires_at,或运行时 token 探测失败(到期)
    REVOKED = "REVOKED"            # 时间未到但被微信踢下线/异地登录/管理员手动置位


# collect_article 合法迁移白名单
COLLECT_TRANSITIONS: dict[str, set[str]] = {
    CollectStatus.COLLECTED: {CollectStatus.MAPPED, CollectStatus.UNMATCHED},
    CollectStatus.MAPPED: {CollectStatus.TRANSFORMED, CollectStatus.UNMATCHED},
    CollectStatus.TRANSFORMED: set(),
    CollectStatus.UNMATCHED: {CollectStatus.MAPPED},  # 人工授权/改规则后可重跑
}

# content_article 合法迁移白名单
ARTICLE_TRANSITIONS: dict[str, set[str]] = {
    ArticleStatus.TRANSFORMED: {ArticleStatus.PENDING_REVIEW, ArticleStatus.APPROVED},
    ArticleStatus.PENDING_REVIEW: {ArticleStatus.APPROVED, ArticleStatus.REJECTED},
    ArticleStatus.REJECTED: {ArticleStatus.PENDING_REVIEW, ArticleStatus.TRANSFORMED},
    ArticleStatus.APPROVED: {ArticleStatus.DRAFT_CREATED},
    ArticleStatus.DRAFT_CREATED: set(),
}

# publish_task 合法迁移白名单(重试 FAILED→SCHEDULED,不回 APPROVED、不重复建稿)
TASK_TRANSITIONS: dict[str, set[str]] = {
    TaskStatus.SCHEDULED: {TaskStatus.PUBLISHING},
    TaskStatus.PUBLISHING: {TaskStatus.PUBLISHED, TaskStatus.FAILED},
    TaskStatus.PUBLISHED: set(),
    TaskStatus.FAILED: {TaskStatus.SCHEDULED},
}

# mp_account 登录态授权 合法迁移白名单(AUTHORIZED 自环=续扫刷新 expires_at)
WX_LOGIN_TRANSITIONS: dict[str, set[str]] = {
    WxLoginStatus.UNAUTHORIZED: {WxLoginStatus.AUTHORIZED},
    WxLoginStatus.AUTHORIZED: {
        WxLoginStatus.EXPIRING, WxLoginStatus.EXPIRED,
        WxLoginStatus.REVOKED, WxLoginStatus.AUTHORIZED,
    },
    WxLoginStatus.EXPIRING: {
        WxLoginStatus.AUTHORIZED, WxLoginStatus.EXPIRED, WxLoginStatus.REVOKED,
    },
    WxLoginStatus.EXPIRED: {WxLoginStatus.AUTHORIZED},   # 重扫复活
    WxLoginStatus.REVOKED: {WxLoginStatus.AUTHORIZED},   # 重扫复活
}

# 表名 → 迁移白名单(key 为逻辑段名;登录态用 mp_account_login 与档案 status 段解耦)
TABLE_TRANSITIONS: dict[str, dict[str, set[str]]] = {
    "collect_article": COLLECT_TRANSITIONS,
    "content_article": ARTICLE_TRANSITIONS,
    "publish_task": TASK_TRANSITIONS,
    "mp_account_login": WX_LOGIN_TRANSITIONS,
}


class IllegalTransition(ValueError):
    def __init__(self, frm: str, to: str):
        super().__init__(f"非法状态迁移: {frm} → {to}")
        self.frm, self.to = frm, to


def can_transition(table: str, frm: str, to: str) -> bool:
    m = TABLE_TRANSITIONS.get(table, {})
    return to in m.get(frm, set())


def ensure_transition(table: str, frm: str, to: str) -> None:
    if not can_transition(table, frm, to):
        raise IllegalTransition(frm, to)
