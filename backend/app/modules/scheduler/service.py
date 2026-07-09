"""调度中心:一次 tick 驱动全自动流水线(对齐设计第 7 章 + M4)。

tick(db, gateway) 一次完整推进(幂等,可被 Celery Beat 或 /scheduler/tick 反复调用):
  1) 采集到期的源(ACTIVE 且 next_run_at 到期)→ collector.run_now
  2) 映射待处理的 COLLECTED → mapping.run_pending(产出 TRANSFORMED content_article)
  3) 自动建任务:对 APPROVED 且无在途任务的 content_article,按 suggested_publish_at 建 SCHEDULED 任务
  4) 发布到期的 SCHEDULED 任务(scheduled_at≤now,dispatched=0)→ 浏览器模拟发表
  5) 重试到期的 FAILED 任务(next_retry_at≤now,retry_count<max_retry)→ 回 SCHEDULED 再发
  6) 死信告警:FAILED 且重试耗尽且未告警 → notifier 告警 + 记 ALERT 日志(幂等)

审核环节不自动跨越:need_review 开时文章停在 PENDING_REVIEW,须人工审核后方进入第 3 步。
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.notifier import notify
from app.core.states import (
    ArticleStatus,
    IllegalTransition,
    TaskStatus,
    WxLoginStatus,
    ensure_transition,
)
from app.models.collect import CollectArticle, CollectSource
from app.models.content import ContentArticle
from app.models.mp_account import MpAccount
from app.models.publish import PublishLog, PublishTask
from app.modules.auth_rbac.deps import UserCtx
from app.modules.auth_rbac.permissions import ALL_PERMS
from app.modules.collector import service as collector_service
from app.modules.content_center import service as content_service
from app.modules.mapping_engine import service as mapping_service
from app.modules.publish_engine import executor
from app.modules.wx_gateway.errors import WX_AUTH_EXPIRED

_LIVE_TASK_STATUSES = (TaskStatus.SCHEDULED, TaskStatus.PUBLISHING, TaskStatus.PUBLISHED)
_ALERT_PHASE = "ALERT"
_MOCK_ACCOUNT_TYPE = 3
_REAL_ACCOUNT_TYPES = (1, 2)  # 订阅号/服务号走真实 BrowserChannel,需登录态授权


def _login_publishable_clause(now: datetime):
    """任务可发的号 = 模拟号 OR (真实号且登录态在授权窗口内)。用于发布/重试队列 SQL 过滤。"""
    return or_(
        MpAccount.account_type == _MOCK_ACCOUNT_TYPE,
        and_(
            MpAccount.wx_login_status.in_(
                [WxLoginStatus.AUTHORIZED, WxLoginStatus.EXPIRING]
            ),
            MpAccount.wx_login_expires_at.is_not(None),
            MpAccount.wx_login_expires_at > now,
        ),
    )

# 系统上下文(自动流水线内代系统提审;super_admin 全权,通过数据权限校验)
_SYSTEM_CTX = UserCtx(id=1, roles=frozenset({"super_admin"}), perms=frozenset(ALL_PERMS))


# ---------------------------------------------------------------------------
# 步骤 2.5:自动提审映射产出的 TRANSFORMED 文章
# (审核开 → PENDING_REVIEW 等人工;审核关 → 自动 APPROVED。审核是有意的人工卡点)
# ---------------------------------------------------------------------------
async def _auto_submit(db: AsyncSession, gateway) -> int:
    articles = (
        await db.scalars(
            select(ContentArticle.id).where(
                ContentArticle.is_deleted == 0,
                ContentArticle.status == ArticleStatus.TRANSFORMED,
                ContentArticle.collect_article_id.is_not(None),  # 仅映射自动产出的稿
                ContentArticle.draft_group_id.is_(None),
            )
        )
    ).all()
    submitted = 0
    for aid in articles:
        try:
            await content_service.submit_article(
                db, article_id=aid, gateway=gateway, current=_SYSTEM_CTX
            )
            submitted += 1
        except Exception:  # noqa: BLE001 —— 单篇提审失败不阻断整批
            continue
    return submitted


# ---------------------------------------------------------------------------
# 步骤 1:采集到期的源
# ---------------------------------------------------------------------------
async def _collect_due(db: AsyncSession, now: datetime) -> tuple[int, int]:
    ids = (
        await db.scalars(
            select(CollectSource.id).where(
                CollectSource.is_deleted == 0,
                CollectSource.status == "ACTIVE",
                or_(CollectSource.next_run_at.is_(None), CollectSource.next_run_at <= now),
            )
        )
    ).all()
    collected = 0
    for sid in ids:
        try:
            r = await collector_service.run_now(db, source_id=sid)
            collected += r.get("collected", 0)
        except Exception:  # noqa: BLE001 —— 单源失败已在 run_now 内处理熔断,不阻断整批
            continue
    return len(ids), collected


# ---------------------------------------------------------------------------
# 步骤 3:自动为 APPROVED 且无在途任务的文章建 SCHEDULED 任务
# ---------------------------------------------------------------------------
async def _auto_create_tasks(db: AsyncSession, now: datetime) -> int:
    articles = (
        await db.scalars(
            select(ContentArticle).where(
                ContentArticle.is_deleted == 0,
                ContentArticle.status == ArticleStatus.APPROVED,
                ContentArticle.draft_group_id.is_(None),  # 组任务由前端显式建,自动流水线只处理单篇
            )
        )
    ).all()
    created = 0
    for art in articles:
        biz_key = f"article:{art.id}"
        # biz_key 唯一:只要存在未删任务(含 FAILED,由重试路径处理)即不重复建
        exists = await db.scalar(
            select(PublishTask.id).where(
                PublishTask.biz_key == biz_key,
                PublishTask.is_deleted == 0,
            )
        )
        if exists:
            continue
        db.add(
            PublishTask(
                biz_key=biz_key,
                content_article_id=art.id,
                mp_account_id=art.mp_account_id,
                publish_type=1,
                scheduled_at=art.suggested_publish_at or now,
                status=TaskStatus.SCHEDULED,
                created_by=art.created_by or 1,
            )
        )
        created += 1
    if created:
        await db.flush()
    return created


# ---------------------------------------------------------------------------
# 步骤 3.5:登录态巡检 —— 时间驱动推进 EXPIRING/EXPIRED + 号级一次续扫告警 + 授权恢复重排
# (对齐 docs/浏览器发布登录态授权设计.md 第 4、6 章)
# ---------------------------------------------------------------------------
async def _login_watch(db: AsyncSession, now: datetime) -> dict:
    warn = timedelta(hours=settings.WX_LOGIN_WARN_HOURS)
    accts = (
        await db.scalars(
            select(MpAccount).where(
                MpAccount.is_deleted == 0,
                MpAccount.account_type.in_(_REAL_ACCOUNT_TYPES),
            )
        )
    ).all()
    transitions = alerts = recovered = 0
    for mp in accts:
        cur = mp.wx_login_status
        exp = mp.wx_login_expires_at
        # 1) 时间驱动:AUTHORIZED/EXPIRING 随 expires_at 推进
        if exp is not None and cur in (WxLoginStatus.AUTHORIZED, WxLoginStatus.EXPIRING):
            if now >= exp:
                target = WxLoginStatus.EXPIRED
            elif now >= exp - warn:
                target = WxLoginStatus.EXPIRING
            else:
                target = WxLoginStatus.AUTHORIZED
            if target != cur:
                try:
                    ensure_transition("mp_account_login", cur, target)
                    mp.wx_login_status = cur = target
                    transitions += 1
                except IllegalTransition:
                    pass
        # 2) 号级一次续扫告警(进入 EXPIRING/EXPIRED/REVOKED 且未告警过)
        if cur in (WxLoginStatus.EXPIRING, WxLoginStatus.EXPIRED, WxLoginStatus.REVOKED) \
                and mp.wx_login_alerted_at is None:
            tip = "即将到期" if cur == WxLoginStatus.EXPIRING else "已失效"
            await notify(
                f"公众号「{mp.mp_name}」浏览器发布登录态{tip},请管理员扫码续期",
                f"app_id={mp.app_id} 状态={cur} 到期={exp};"
                f"在部署机执行: python scripts/wx_login.py {mp.app_id}",
            )
            mp.wx_login_alerted_at = now
            alerts += 1
        # 3) 授权恢复重排:号在窗口内 → 其因登录态过期挂起的 FAILED 任务回 SCHEDULED(不计重试)
        if cur in (WxLoginStatus.AUTHORIZED, WxLoginStatus.EXPIRING):
            stuck = (
                await db.scalars(
                    select(PublishTask).where(
                        PublishTask.is_deleted == 0,
                        PublishTask.mp_account_id == mp.id,
                        PublishTask.status == TaskStatus.FAILED,
                        PublishTask.last_errcode == WX_AUTH_EXPIRED,
                    )
                )
            ).all()
            for t in stuck:
                try:
                    ensure_transition("publish_task", t.status, TaskStatus.SCHEDULED)
                    t.status = TaskStatus.SCHEDULED
                    t.dispatched = 0
                    t.last_errcode = None
                    t.last_errmsg = ""
                    t.next_retry_at = None
                    recovered += 1
                except IllegalTransition:
                    pass
    await db.flush()
    return {"login_transitions": transitions, "login_alerts": alerts, "login_recovered": recovered}


# ---------------------------------------------------------------------------
# 步骤 4:发布到期的 SCHEDULED 任务(过期号任务经 SQL 过滤直接跳过,原地挂起)
# ---------------------------------------------------------------------------
async def _publish_due(db: AsyncSession, gateway, now: datetime) -> tuple[int, int]:
    tasks = (
        await db.scalars(
            select(PublishTask)
            .join(MpAccount, MpAccount.id == PublishTask.mp_account_id)
            .where(
                PublishTask.is_deleted == 0,
                PublishTask.status == TaskStatus.SCHEDULED,
                PublishTask.dispatched == 0,
                PublishTask.scheduled_at <= now,
                _login_publishable_clause(now),
            )
        )
    ).all()
    published = failed = 0
    for task in tasks:
        await executor.execute_publish(db, gateway, task)
        if task.status == TaskStatus.PUBLISHED:
            published += 1
        elif task.status == TaskStatus.FAILED:
            failed += 1
    return published, failed


# ---------------------------------------------------------------------------
# 步骤 5:重试到期的 FAILED 任务
# ---------------------------------------------------------------------------
async def _retry_due(db: AsyncSession, gateway, now: datetime) -> int:
    tasks = (
        await db.scalars(
            select(PublishTask)
            .join(MpAccount, MpAccount.id == PublishTask.mp_account_id)
            .where(
                PublishTask.is_deleted == 0,
                PublishTask.status == TaskStatus.FAILED,
                PublishTask.next_retry_at.is_not(None),
                PublishTask.next_retry_at <= now,
                PublishTask.retry_count < PublishTask.max_retry,
                _login_publishable_clause(now),
            )
        )
    ).all()
    retried = 0
    for task in tasks:
        ensure_transition("publish_task", task.status, TaskStatus.SCHEDULED)
        task.status = TaskStatus.SCHEDULED
        task.retry_count += 1
        task.dispatched = 0
        task.last_errcode = None
        task.last_errmsg = ""
        task.next_retry_at = None
        await db.flush()
        await executor.execute_publish(db, gateway, task)
        retried += 1
    return retried


# ---------------------------------------------------------------------------
# 步骤 6:死信告警(重试耗尽且未告警过)
# ---------------------------------------------------------------------------
async def _dead_letter_alerts(db: AsyncSession) -> int:
    tasks = (
        await db.scalars(
            select(PublishTask).where(
                PublishTask.is_deleted == 0,
                PublishTask.status == TaskStatus.FAILED,
                PublishTask.retry_count >= PublishTask.max_retry,
            )
        )
    ).all()
    alerted = 0
    for task in tasks:
        already = await db.scalar(
            select(PublishLog.id).where(
                PublishLog.publish_task_id == task.id, PublishLog.phase == _ALERT_PHASE
            )
        )
        if already:
            continue
        await notify(
            f"发布任务 #{task.id} 重试耗尽已进入死信",
            f"公众号 {task.mp_account_id},最后错误: [{task.last_errcode}] {task.last_errmsg}",
        )
        db.add(
            PublishLog(
                publish_task_id=task.id, phase=_ALERT_PHASE,
                wx_api="", request_digest="dead-letter alert sent",
                errcode=task.last_errcode, errmsg=task.last_errmsg or "", cost_ms=0,
            )
        )
        alerted += 1
    if alerted:
        await db.flush()
    return alerted


# ---------------------------------------------------------------------------
# 一次 tick
# ---------------------------------------------------------------------------
async def tick(db: AsyncSession, gateway) -> dict:
    now = datetime.utcnow()
    sources_due, collected = await _collect_due(db, now)
    mapped = await mapping_service.run_pending(db, limit=500)
    submitted = await _auto_submit(db, gateway)
    auto_tasks = await _auto_create_tasks(db, now)
    login = await _login_watch(db, now)  # 登录态巡检:推进/告警/恢复重排,须在发布前
    published, failed = await _publish_due(db, gateway, now)
    retried = await _retry_due(db, gateway, now)
    alerted = await _dead_letter_alerts(db)
    await db.commit()
    return {
        "sources_due": sources_due,
        "collected": collected,
        "mapped_transformed": mapped.get("transformed", 0),
        "auto_submitted": submitted,
        "auto_created_tasks": auto_tasks,
        "published": published,
        "failed": failed,
        "retried": retried,
        "dead_letter_alerts": alerted,
        **login,
    }


# ---------------------------------------------------------------------------
# 看板聚合(各引擎状态计数 + 发布成功率)
# ---------------------------------------------------------------------------
async def _count_by_status(db: AsyncSession, col, model) -> dict:
    rows = await db.execute(
        select(col, func.count()).where(model.is_deleted == 0).group_by(col)
    )
    return {str(s): c for s, c in rows.all()}


async def dashboard(db: AsyncSession) -> dict:
    collect_by = await _count_by_status(db, CollectArticle.status, CollectArticle)
    content_by = await _count_by_status(db, ContentArticle.status, ContentArticle)
    task_by = await _count_by_status(db, PublishTask.status, PublishTask)

    sources_total = await db.scalar(
        select(func.count()).select_from(CollectSource).where(CollectSource.is_deleted == 0)
    )
    sources_circuit = await db.scalar(
        select(func.count()).select_from(CollectSource).where(
            CollectSource.is_deleted == 0, CollectSource.status == "CIRCUIT_OPEN"
        )
    )
    mp_total = await db.scalar(
        select(func.count()).select_from(MpAccount).where(MpAccount.is_deleted == 0)
    )
    # 真实号登录态授权分布(教学 Mock 号 account_type=3 无需授权,不计入)
    login_rows = await db.execute(
        select(MpAccount.wx_login_status, func.count())
        .where(MpAccount.is_deleted == 0, MpAccount.account_type.in_(_REAL_ACCOUNT_TYPES))
        .group_by(MpAccount.wx_login_status)
    )
    wx_login_by = {str(s): c for s, c in login_rows.all()}

    published = task_by.get(TaskStatus.PUBLISHED, 0)
    failed = task_by.get(TaskStatus.FAILED, 0)
    terminal = published + failed
    success_rate = round(published / terminal * 100, 2) if terminal else 0.0

    return {
        "mp_total": mp_total or 0,
        "sources_total": sources_total or 0,
        "sources_circuit": sources_circuit or 0,
        "collect_by_status": collect_by,
        "content_by_status": content_by,
        "task_by_status": task_by,
        "publish_success_rate": success_rate,
        "pending_review": content_by.get(ArticleStatus.PENDING_REVIEW, 0),
        "wx_login_by_status": wx_login_by,
    }
