"""映射引擎核心执行(内联,不用 Celery)。

process_collect_article(db, collect_article_id) 单篇处理:
  1) 幂等:仅 status==COLLECTED 继续。
  2) 原创拦截:art.is_original_marked==1 且 source.whitelist_confirmed==0
     → COLLECTED→UNMATCHED,unmatched_reason="原创未确认授权"。
  3) 候选规则:经 mapping_rule_source 关联 source_id 且 enabled=1 且未删,
     按 priority DESC, id ASC。
  4) evaluate 匹配;冲突消解:同 target_mp_account_id 只留 priority 最高一条。
  5) 每个 winner:uk_collect_mp 去重 → apply_transform → 计算 suggested_publish_at
     → create content_article(status=TRANSFORMED)。
  6) 状态推进:produced>=1 → COLLECTED→MAPPED→TRANSFORMED;
     produced==0 → COLLECTED→UNMATCHED。

content_article 产出即 TRANSFORMED(不自动提审,交运营在内容中心走提审/审核/发布)。
"""
from __future__ import annotations

import json
from datetime import datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.states import ArticleStatus, CollectStatus, ensure_transition
from app.models.collect import CollectArticle, CollectSource
from app.models.content import ContentArticle
from app.models.mapping import MappingRule, MappingRuleSource
from app.modules.mapping_engine import matcher, transform


def _loads(text: str | None) -> dict:
    """安全解析 JSON 字符串字段为 dict;空/非法 → {}。"""
    if not text:
        return {}
    try:
        v = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return {}
    return v if isinstance(v, dict) else {}


def _digest_from(content_html: str, fallback: str = "") -> str:
    """由正文纯文本取前 120 字作摘要(content_article.digest 上限 120)。"""
    from app.core.simhash import html_to_text

    text = html_to_text(content_html) or fallback
    return text[:120]


# ---------------------------------------------------------------------------
# 排期:schedule_policy 简化实现
# ---------------------------------------------------------------------------
def compute_suggested_publish_at(
    policy: dict,
    *,
    same_day_count: int,
    now: datetime | None = None,
) -> datetime | None:
    """取今天 time_windows 首个窗口起点作为建议发布时刻。

    schedule_policy 约定:
    - time_windows: [{start: "HH:MM"}, ...]  取首个窗口的 start
    - daily_limit: int  当天已产出 >= daily_limit 时溢出
    - overflow: "NEXT_DAY" | "DROP"  溢出策略,默认 NEXT_DAY
    无 time_windows → 返回 None(不预设发布时刻,由运营手工排)。
    """
    now = now or datetime.now()
    windows = policy.get("time_windows") or []
    if not windows or not isinstance(windows, list):
        return None

    first = windows[0]
    start_str = first.get("start") if isinstance(first, dict) else None
    if not start_str:
        return None
    try:
        hh, mm = str(start_str).split(":")[:2]
        start_t = time(int(hh), int(mm))
    except (ValueError, TypeError):
        return None

    daily_limit = policy.get("daily_limit")
    overflow = (policy.get("overflow") or "NEXT_DAY").upper()

    day = now.date()
    if isinstance(daily_limit, int) and daily_limit > 0 and same_day_count >= daily_limit:
        if overflow == "DROP":
            return None
        day = day + timedelta(days=1)  # NEXT_DAY 顺延

    return datetime.combine(day, start_t)


async def _count_same_day_for_target(
    db: AsyncSession, *, mp_account_id: int, day_start: datetime
) -> int:
    """当天已排到该目标号的 content_article 数量(用于 daily_limit 判满)。"""
    day_end = day_start + timedelta(days=1)
    rows = await db.scalars(
        select(ContentArticle.id).where(
            ContentArticle.mp_account_id == mp_account_id,
            ContentArticle.is_deleted == 0,
            ContentArticle.suggested_publish_at >= day_start,
            ContentArticle.suggested_publish_at < day_end,
        )
    )
    return len(rows.all())


async def process_collect_article(db: AsyncSession, collect_article_id: int) -> dict:
    """单篇采集文章的映射执行。返回处理结果 dict;写操作在本函数内 commit。"""
    art = await db.get(CollectArticle, collect_article_id)
    if art is None or art.is_deleted:
        return {"status": "SKIPPED", "reason": "采集文章不存在", "produced": 0,
                "content_article_ids": []}

    # 1) 幂等:仅 COLLECTED 继续
    if art.status != CollectStatus.COLLECTED:
        return {"status": art.status, "reason": "非 COLLECTED,跳过", "produced": 0,
                "content_article_ids": []}

    source = await db.get(CollectSource, art.source_id)

    # 2) 原创拦截
    if art.is_original_marked == 1 and (source is None or source.whitelist_confirmed == 0):
        ensure_transition("collect_article", art.status, CollectStatus.UNMATCHED)
        art.status = CollectStatus.UNMATCHED
        art.unmatched_reason = "原创未确认授权"
        await db.commit()
        return {"status": CollectStatus.UNMATCHED, "reason": "原创未确认授权",
                "produced": 0, "content_article_ids": []}

    # 3) 候选规则:经 mapping_rule_source 关联 source_id 且 enabled 且未删,priority DESC, id ASC
    rules = (
        await db.scalars(
            select(MappingRule)
            .join(MappingRuleSource, MappingRuleSource.rule_id == MappingRule.id)
            .where(
                MappingRuleSource.source_id == art.source_id,
                MappingRule.enabled == 1,
                MappingRule.is_deleted == 0,
            )
            .order_by(MappingRule.priority.desc(), MappingRule.id.asc())
        )
    ).all()

    # 4) evaluate 匹配 + 冲突消解:同 target_mp_account_id 只留 priority 最高一条
    #    规则已按 priority DESC, id ASC 排序,首次遇到某 target 即为该号赢家。
    winner_by_target: dict[int, MappingRule] = {}
    for rule in rules:
        cond = _loads(rule.match_condition_json)
        if not matcher.evaluate(cond, art):
            continue
        if rule.target_mp_account_id not in winner_by_target:
            winner_by_target[rule.target_mp_account_id] = rule

    source_name = source.source_name if source is not None else ""
    produced_ids: list[int] = []

    # 5) 逐 winner 产出 content_article
    for target_mp_id, rule in winner_by_target.items():
        # uk_collect_mp 去重:已存在同 (collect_article_id, mp_account_id) 则跳过
        exists = await db.scalar(
            select(ContentArticle.id).where(
                ContentArticle.collect_article_id == art.id,
                ContentArticle.mp_account_id == target_mp_id,
            )
        )
        if exists is not None:
            continue

        action = _loads(rule.transform_action_json)
        title, content_html = transform.apply_transform(action, art, source_name)

        policy = _loads(rule.schedule_policy_json)
        now = datetime.now()
        day_start = datetime.combine(now.date(), time.min)
        same_day_count = await _count_same_day_for_target(
            db, mp_account_id=target_mp_id, day_start=day_start
        )
        suggested_at = compute_suggested_publish_at(
            policy, same_day_count=same_day_count, now=now
        )

        content = ContentArticle(
            mp_account_id=target_mp_id,
            collect_article_id=art.id,
            mapping_rule_id=rule.id,
            title=title or (art.title or "")[:64],
            author=(art.author or "")[:64],
            digest=_digest_from(content_html, art.digest or ""),
            content_html=content_html,
            cover_material_id=None,
            content_source_url=(art.url or "")[:512],
            suggested_publish_at=suggested_at,
            is_original_marked=art.is_original_marked,
            status=ArticleStatus.TRANSFORMED,
            created_by=rule.created_by,
        )
        db.add(content)
        await db.flush()
        produced_ids.append(content.id)

    produced = len(produced_ids)

    # 6) 状态推进
    if produced >= 1:
        ensure_transition("collect_article", art.status, CollectStatus.MAPPED)
        art.status = CollectStatus.MAPPED
        ensure_transition("collect_article", art.status, CollectStatus.TRANSFORMED)
        art.status = CollectStatus.TRANSFORMED
        art.unmatched_reason = ""
        final_status = CollectStatus.TRANSFORMED
    else:
        ensure_transition("collect_article", art.status, CollectStatus.UNMATCHED)
        art.status = CollectStatus.UNMATCHED
        art.unmatched_reason = "无规则命中或均被去重"
        final_status = CollectStatus.UNMATCHED

    await db.commit()
    return {
        "status": final_status,
        "produced": produced,
        "content_article_ids": produced_ids,
    }
