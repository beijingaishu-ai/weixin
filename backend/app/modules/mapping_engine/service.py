"""mapping-engine 业务逻辑:规则 CRUD + dry-run + preview + run-pending + executions。

约定(对齐 M1/M2/M3 地基):
- JSON 配置字段(match_condition/transform_action/schedule_policy)在库里存 JSON 字符串;
  入库 json.dumps,出参 json.loads 还原为对象。
- source_ids 展开写 mapping_rule_source(唯一键 rule_id+source_id);PUT 全量重建。
- 状态迁移一律经 engine.process_collect_article 内的 ensure_transition。
- 逻辑删:MappingRule.is_deleted=1;有关联 content_article(mapping_rule_id 指向本规则)禁物理删。
- 分页统一 {items, total, page, page_size};写操作 commit。
"""
from __future__ import annotations

import json

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.core.states import CollectStatus
from app.models.collect import CollectArticle
from app.models.content import ContentArticle
from app.models.mapping import MappingRule, MappingRuleSource
from app.models.mp_account import MpAccount
from app.modules.mapping_engine import engine, matcher, schemas, transform


# ===========================================================================
# 通用助手
# ===========================================================================
async def _get_rule_or_404(db: AsyncSession, rule_id: int) -> MappingRule:
    rule = await db.get(MappingRule, rule_id)
    if rule is None or rule.is_deleted:
        raise AppError("映射规则不存在", code=1, status_code=404)
    return rule


async def _assert_mp_exists(db: AsyncSession, mp_id: int) -> None:
    mp = await db.get(MpAccount, mp_id)
    if mp is None or mp.is_deleted:
        raise AppError("目标公众号不存在", code=1, status_code=404)


async def _source_ids_of(db: AsyncSession, rule_id: int) -> list[int]:
    rows = await db.scalars(
        select(MappingRuleSource.source_id)
        .where(MappingRuleSource.rule_id == rule_id)
        .order_by(MappingRuleSource.source_id.asc())
    )
    return list(rows.all())


async def _replace_rule_sources(
    db: AsyncSession, rule_id: int, source_ids: list[int]
) -> None:
    """重建 mapping_rule_source:先删净该规则的关联,再按去重后的 source_ids 写入。"""
    await db.execute(
        delete(MappingRuleSource).where(MappingRuleSource.rule_id == rule_id)
    )
    seen: set[int] = set()
    for sid in source_ids:
        if sid in seen:
            continue
        seen.add(sid)
        db.add(MappingRuleSource(rule_id=rule_id, source_id=sid))
    await db.flush()


def _loads(text: str | None) -> dict:
    if not text:
        return {}
    try:
        v = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return {}
    return v if isinstance(v, dict) else {}


def _rule_to_item(rule: MappingRule, source_ids: list[int]) -> dict:
    return {
        "id": rule.id,
        "rule_name": rule.rule_name,
        "target_mp_account_id": rule.target_mp_account_id,
        "source_ids": source_ids,
        "match_condition_json": _loads(rule.match_condition_json),
        "transform_action_json": _loads(rule.transform_action_json),
        "schedule_policy_json": _loads(rule.schedule_policy_json),
        "priority": rule.priority,
        "enabled": rule.enabled,
        "created_by": rule.created_by,
        "created_at": rule.created_at,
        "updated_at": rule.updated_at,
    }


# ===========================================================================
# 规则 CRUD
# ===========================================================================
async def list_rules(
    db: AsyncSession,
    *,
    page: int,
    page_size: int,
    source_id: int | None,
    target_mp_account_id: int | None,
    enabled: int | None,
    keyword: str | None,
) -> dict:
    base = select(MappingRule).where(MappingRule.is_deleted == 0)
    if source_id is not None:
        base = base.join(
            MappingRuleSource, MappingRuleSource.rule_id == MappingRule.id
        ).where(MappingRuleSource.source_id == source_id)
    if target_mp_account_id is not None:
        base = base.where(MappingRule.target_mp_account_id == target_mp_account_id)
    if enabled is not None:
        base = base.where(MappingRule.enabled == enabled)
    if keyword:
        base = base.where(MappingRule.rule_name.like(f"%{keyword.strip()}%"))

    total = await db.scalar(
        select(func.count()).select_from(base.order_by(None).subquery())
    )
    rows = await db.scalars(
        base.order_by(MappingRule.priority.desc(), MappingRule.id.desc())
        .limit(page_size)
        .offset((page - 1) * page_size)
    )
    rules = rows.all()

    items = []
    for rule in rules:
        sids = await _source_ids_of(db, rule.id)
        items.append(_rule_to_item(rule, sids))
    return {"items": items, "total": total or 0, "page": page, "page_size": page_size}


async def create_rule(
    db: AsyncSession, *, payload: schemas.RuleCreate, current_id: int
) -> dict:
    await _assert_mp_exists(db, payload.target_mp_account_id)

    rule = MappingRule(
        rule_name=payload.rule_name,
        target_mp_account_id=payload.target_mp_account_id,
        match_condition_json=json.dumps(payload.match_condition_json, ensure_ascii=False),
        transform_action_json=json.dumps(payload.transform_action_json, ensure_ascii=False),
        schedule_policy_json=json.dumps(payload.schedule_policy_json, ensure_ascii=False),
        priority=payload.priority,
        enabled=payload.enabled,
        created_by=current_id,
    )
    db.add(rule)
    await db.flush()
    await _replace_rule_sources(db, rule.id, payload.source_ids)
    await db.commit()
    return {"id": rule.id}


async def get_rule(db: AsyncSession, *, rule_id: int) -> dict:
    rule = await _get_rule_or_404(db, rule_id)
    sids = await _source_ids_of(db, rule.id)
    return _rule_to_item(rule, sids)


async def update_rule(
    db: AsyncSession, *, rule_id: int, payload: schemas.RuleUpdate
) -> None:
    rule = await _get_rule_or_404(db, rule_id)
    await _assert_mp_exists(db, payload.target_mp_account_id)

    rule.rule_name = payload.rule_name
    rule.target_mp_account_id = payload.target_mp_account_id
    rule.match_condition_json = json.dumps(payload.match_condition_json, ensure_ascii=False)
    rule.transform_action_json = json.dumps(payload.transform_action_json, ensure_ascii=False)
    rule.schedule_policy_json = json.dumps(payload.schedule_policy_json, ensure_ascii=False)
    rule.priority = payload.priority
    rule.enabled = payload.enabled

    await _replace_rule_sources(db, rule.id, payload.source_ids)
    await db.commit()


async def set_rule_status(db: AsyncSession, *, rule_id: int, enabled: int) -> None:
    rule = await _get_rule_or_404(db, rule_id)
    rule.enabled = enabled
    await db.commit()


async def delete_rule(db: AsyncSession, *, rule_id: int) -> None:
    """逻辑删。有 content_article 引用本规则(mapping_rule_id)时禁物理删——本就逻辑删,记留痕即可。"""
    rule = await _get_rule_or_404(db, rule_id)
    # 仅逻辑删;关联的 content_article 保留(mapping_rule_id 指向已删规则不影响历史产物)
    rule.is_deleted = 1
    # 逻辑删同时清空源关联,避免重跑时误命中已删规则
    await db.execute(
        delete(MappingRuleSource).where(MappingRuleSource.rule_id == rule.id)
    )
    await db.commit()


# ===========================================================================
# dry-run / preview
# ===========================================================================
class _SampleArticle:
    """dry-run 的轻量文章占位:仅提供 matcher 需要的 title / clean_html 属性。"""

    def __init__(self, title: str = "", content: str = ""):
        self.title = title
        self.clean_html = content
        self.author = ""
        self.url = ""
        self.digest = ""
        self.source_publish_time = None
        self.is_original_marked = 0


async def dry_run(db: AsyncSession, *, payload: schemas.DryRunIn) -> dict:
    """对条件做命中测试:优先 collect_article_id,否则用 sample。"""
    if payload.collect_article_id is not None:
        art = await db.get(CollectArticle, payload.collect_article_id)
        if art is None or art.is_deleted:
            raise AppError("采集文章不存在", code=1, status_code=404)
    else:
        s = payload.sample or schemas.DryRunSample()
        art = _SampleArticle(title=s.title, content=s.content)

    return matcher.evaluate_detail(payload.match_condition_json, art)


async def preview(db: AsyncSession, *, rule_id: int, collect_article_id: int) -> dict:
    """对某采集文章套用规则转换,返回渲染后 title/content_html,不落库。"""
    rule = await _get_rule_or_404(db, rule_id)
    art = await db.get(CollectArticle, collect_article_id)
    if art is None or art.is_deleted:
        raise AppError("采集文章不存在", code=1, status_code=404)

    # 取源名(preview 用第一个关联源名即可;找不到留空)
    source_name = ""
    from app.models.collect import CollectSource

    src = await db.get(CollectSource, art.source_id)
    if src is not None:
        source_name = src.source_name

    action = _loads(rule.transform_action_json)
    title, content_html = transform.apply_transform(action, art, source_name)
    return {"title": title, "content_html": content_html}


# ===========================================================================
# run-pending
# ===========================================================================
async def run_pending(db: AsyncSession, *, limit: int) -> dict:
    """对所有 status=COLLECTED 的 collect_article 逐个 process_collect_article。"""
    ids = (
        await db.scalars(
            select(CollectArticle.id)
            .where(
                CollectArticle.status == CollectStatus.COLLECTED,
                CollectArticle.is_deleted == 0,
            )
            .order_by(CollectArticle.id.asc())
            .limit(limit)
        )
    ).all()

    processed = mapped = transformed = unmatched = produced_content = 0
    for cid in ids:
        result = await engine.process_collect_article(db, cid)
        processed += 1
        status = result.get("status")
        produced = result.get("produced", 0)
        produced_content += produced
        if status == CollectStatus.TRANSFORMED:
            transformed += 1
            mapped += 1  # 产出必经 MAPPED→TRANSFORMED,计入命中
        elif status == CollectStatus.UNMATCHED:
            unmatched += 1

    return {
        "processed": processed,
        "mapped": mapped,
        "transformed": transformed,
        "unmatched": unmatched,
        "produced_content": produced_content,
    }


# ===========================================================================
# executions:按有 mapping_rule_id 的 content_article 列出产出记录
# ===========================================================================
async def list_executions(db: AsyncSession, *, page: int, page_size: int) -> dict:
    base = select(ContentArticle).where(
        ContentArticle.mapping_rule_id.is_not(None),
        ContentArticle.is_deleted == 0,
    )
    total = await db.scalar(
        select(func.count()).select_from(base.order_by(None).subquery())
    )
    rows = await db.scalars(
        base.order_by(ContentArticle.id.desc())
        .limit(page_size)
        .offset((page - 1) * page_size)
    )
    items = []
    for c in rows.all():
        items.append(
            {
                "content_article_id": c.id,
                "collect_article_id": c.collect_article_id,
                "mapping_rule_id": c.mapping_rule_id,
                "target_mp_account_id": c.mp_account_id,
                "title": c.title,
                "status": c.status,
                "suggested_publish_at": c.suggested_publish_at,
                "created_at": c.created_at,
            }
        )
    return {"items": items, "total": total or 0, "page": page, "page_size": page_size}
