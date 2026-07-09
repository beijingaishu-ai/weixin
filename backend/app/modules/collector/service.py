"""collector 业务逻辑:采集源 CRUD + run-now 采集流程 + 手工导入 + 文章库 + 统计。"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.core.simhash import normalize_title, url_hash
from app.core.states import CollectStatus
from app.models.collect import CollectArticle, CollectSource
from app.modules.collector import dedup
from app.modules.collector.adapters import ADAPTER_REGISTRY
from app.modules.collector.cleaning import clean_html

CIRCUIT_THRESHOLD = 5


# =========================================================================
# 助手
# =========================================================================
def _loads(text: str | None) -> dict:
    if not text:
        return {}
    try:
        v = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return {}
    return v if isinstance(v, dict) else {}


def _parse_dt(s: str) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00").replace("/", "-"))
    except ValueError:
        return None


async def _get_source(db: AsyncSession, source_id: int) -> CollectSource:
    src = await db.get(CollectSource, source_id)
    if src is None or src.is_deleted:
        raise AppError("采集源不存在", code=1, status_code=404)
    return src


def _source_item(src: CollectSource) -> dict:
    return {
        "id": src.id,
        "source_name": src.source_name,
        "adapter_type": src.adapter_type,
        "config_json": _loads(src.config_json),
        "interval_minutes": src.interval_minutes,
        "jitter_seconds": src.jitter_seconds,
        "whitelist_confirmed": src.whitelist_confirmed,
        "auth_proof_url": src.auth_proof_url,
        "status": src.status,
        "fail_count": src.fail_count,
        "next_run_at": src.next_run_at,
        "created_at": src.created_at,
    }


# =========================================================================
# 采集源 CRUD
# =========================================================================
async def list_sources(
    db: AsyncSession, *, page: int, page_size: int,
    adapter_type: str | None, status: str | None, keyword: str | None,
) -> dict:
    base = select(CollectSource).where(CollectSource.is_deleted == 0)
    if adapter_type:
        base = base.where(CollectSource.adapter_type == adapter_type)
    if status:
        base = base.where(CollectSource.status == status)
    if keyword:
        base = base.where(CollectSource.source_name.like(f"%{keyword.strip()}%"))
    total = await db.scalar(select(func.count()).select_from(base.order_by(None).subquery()))
    rows = await db.scalars(
        base.order_by(CollectSource.id.desc()).limit(page_size).offset((page - 1) * page_size)
    )
    return {
        "items": [_source_item(s) for s in rows.all()],
        "total": total or 0, "page": page, "page_size": page_size,
    }


async def create_source(db: AsyncSession, *, payload, current_id: int) -> dict:
    if payload.adapter_type not in ADAPTER_REGISTRY:
        raise AppError(f"未知适配器类型: {payload.adapter_type}", status_code=422)
    src = CollectSource(
        source_name=payload.source_name,
        adapter_type=payload.adapter_type,
        config_json=json.dumps(payload.config_json, ensure_ascii=False),
        interval_minutes=payload.interval_minutes,
        jitter_seconds=payload.jitter_seconds,
        whitelist_confirmed=payload.whitelist_confirmed,
        auth_proof_url=payload.auth_proof_url,
        status="ACTIVE",
        created_by=current_id,
    )
    db.add(src)
    await db.commit()
    return {"id": src.id}


async def get_source(db: AsyncSession, *, source_id: int) -> dict:
    return _source_item(await _get_source(db, source_id))


async def update_source(db: AsyncSession, *, source_id: int, payload) -> None:
    src = await _get_source(db, source_id)
    if payload.source_name is not None:
        src.source_name = payload.source_name
    if payload.config_json is not None:
        src.config_json = json.dumps(payload.config_json, ensure_ascii=False)
    if payload.interval_minutes is not None:
        src.interval_minutes = payload.interval_minutes
    if payload.jitter_seconds is not None:
        src.jitter_seconds = payload.jitter_seconds
    if payload.whitelist_confirmed is not None:
        src.whitelist_confirmed = payload.whitelist_confirmed
    if payload.auth_proof_url is not None:
        src.auth_proof_url = payload.auth_proof_url
    await db.commit()


async def delete_source(db: AsyncSession, *, source_id: int) -> None:
    src = await _get_source(db, source_id)
    src.is_deleted = 1
    await db.commit()


async def set_enabled(db: AsyncSession, *, source_id: int, enabled: bool) -> None:
    src = await _get_source(db, source_id)
    if enabled:
        src.status = "ACTIVE"
        src.fail_count = 0
    else:
        src.status = "PAUSED"
    await db.commit()


# =========================================================================
# test-run / run-now(核心采集)
# =========================================================================
async def test_run(db: AsyncSession, *, source_id: int) -> dict:
    src = await _get_source(db, source_id)
    cls = ADAPTER_REGISTRY.get(src.adapter_type)
    if cls is None:
        raise AppError("未知适配器", status_code=422)
    adapter = cls(_loads(src.config_json))
    try:
        ok = await adapter.healthcheck()
        metas, _ = await adapter.fetch_list({})
        sample = None
        if metas:
            d = await adapter.fetch_detail(metas[0])
            sample = {"title": d.title, "author": d.author, "url": d.url,
                      "is_original_marked": d.is_original_marked}
        return {"ok": bool(ok), "sample": sample, "hint": f"试拉 {len(metas)} 条(未入库)"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "sample": None, "hint": f"自检失败: {e}"}


async def run_now(db: AsyncSession, *, source_id: int) -> dict:
    src = await _get_source(db, source_id)
    if src.status == "PAUSED":
        raise AppError("采集源已停用,请先启用", status_code=422)
    cls = ADAPTER_REGISTRY.get(src.adapter_type)
    if cls is None:
        raise AppError("未知适配器", status_code=422)
    adapter = cls(_loads(src.config_json))

    collected = duplicated = 0
    try:
        metas, new_cursor = await adapter.fetch_list(_loads(src.cursor_json))
        for meta in metas:
            detail = await adapter.fetch_detail(meta)
            cleaned, text = clean_html(detail.raw_html)
            dup_kind, dedup_of = await dedup.dedup_check(
                db, url=detail.url, title=detail.title, clean_text=text
            )
            if dup_kind == "url":
                duplicated += 1
                continue  # URL 精确重复:url_hash 唯一约束,不二次入库

            uh = url_hash(detail.url, fallback=normalize_title(detail.title) + text[:200])
            sh_hex, b0, b1, b2, b3 = dedup.compute_fingerprint(text)
            is_content_dup = dup_kind == "content"
            art = CollectArticle(
                source_id=src.id,
                title=detail.title[:255],
                author=detail.author[:64],
                url=detail.url[:1024],
                url_hash=uh,
                simhash=sh_hex, simhash_b0=b0, simhash_b1=b1, simhash_b2=b2, simhash_b3=b3,
                dedup_of=dedup_of if is_content_dup else None,
                digest=text[:255],
                raw_html=detail.raw_html,
                clean_html=cleaned,
                cover_url=detail.cover_url[:512],
                is_original_marked=1 if detail.is_original_marked else 0,
                unmatched_reason="内容重复" if is_content_dup else "",
                source_publish_time=_parse_dt(detail.pub_time),
                status=CollectStatus.UNMATCHED if is_content_dup else CollectStatus.COLLECTED,
            )
            try:
                async with db.begin_nested():
                    db.add(art)
                    await db.flush()
            except IntegrityError:
                duplicated += 1  # 并发下 url_hash 撞唯一键 → 计为重复
                continue
            if is_content_dup:
                duplicated += 1
            else:
                collected += 1

        src.cursor_json = json.dumps(new_cursor, ensure_ascii=False)
        src.fail_count = 0
        if src.status == "CIRCUIT_OPEN":
            src.status = "ACTIVE"
        src.next_run_at = datetime.now() + timedelta(minutes=src.interval_minutes)
        await db.commit()
    except AppError:
        raise
    except Exception as e:  # noqa: BLE001
        src.fail_count += 1
        if src.fail_count >= CIRCUIT_THRESHOLD:
            src.status = "CIRCUIT_OPEN"
        await db.commit()
        raise AppError(f"采集失败: {e}", status_code=502)

    return {"collected": collected, "duplicated": duplicated, "total": collected + duplicated}


async def manual_import(db: AsyncSession, *, payload, current_id: int) -> dict:
    src = await _get_source(db, payload.source_id)
    cleaned, text = clean_html(payload.raw_html)
    dup_kind, dedup_of = await dedup.dedup_check(
        db, url=payload.url, title=payload.title, clean_text=text
    )
    if dup_kind == "url":
        raise AppError("该 URL 已采集,勿重复导入", status_code=409)
    uh = url_hash(payload.url, fallback=normalize_title(payload.title) + text[:200])
    sh_hex, b0, b1, b2, b3 = dedup.compute_fingerprint(text)
    is_content_dup = dup_kind == "content"
    art = CollectArticle(
        source_id=src.id, title=payload.title[:255], author=payload.author[:64],
        url=payload.url[:1024], url_hash=uh,
        simhash=sh_hex, simhash_b0=b0, simhash_b1=b1, simhash_b2=b2, simhash_b3=b3,
        dedup_of=dedup_of if is_content_dup else None,
        digest=text[:255], raw_html=payload.raw_html, clean_html=cleaned,
        is_original_marked=payload.is_original_marked,
        unmatched_reason="内容重复" if is_content_dup else "",
        status=CollectStatus.UNMATCHED if is_content_dup else CollectStatus.COLLECTED,
    )
    db.add(art)
    await db.commit()
    return {"id": art.id}


# =========================================================================
# 文章库
# =========================================================================
async def list_articles(
    db: AsyncSession, *, page: int, page_size: int,
    source_id: int | None, status: str | None, keyword: str | None,
) -> dict:
    base = select(CollectArticle).where(CollectArticle.is_deleted == 0)
    if source_id is not None:
        base = base.where(CollectArticle.source_id == source_id)
    if status:
        base = base.where(CollectArticle.status == status)
    if keyword:
        base = base.where(CollectArticle.title.like(f"%{keyword.strip()}%"))
    total = await db.scalar(select(func.count()).select_from(base.order_by(None).subquery()))
    rows = await db.scalars(
        base.order_by(CollectArticle.id.desc()).limit(page_size).offset((page - 1) * page_size)
    )
    return {
        "items": [a for a in rows.all()],
        "total": total or 0, "page": page, "page_size": page_size,
    }


async def get_article(db: AsyncSession, *, article_id: int) -> CollectArticle:
    art = await db.get(CollectArticle, article_id)
    if art is None or art.is_deleted:
        raise AppError("采集文章不存在", code=1, status_code=404)
    return art


async def dedup_info(db: AsyncSession, *, article_id: int) -> dict:
    art = await get_article(db, article_id=article_id)
    hamming_to_dup = None
    hint = "无重复"
    if art.dedup_of:
        orig = await db.get(CollectArticle, art.dedup_of)
        if orig is not None:
            try:
                from app.core.simhash import hamming
                hamming_to_dup = hamming(int(art.simhash, 16), int(orig.simhash, 16))
            except (ValueError, TypeError):
                hamming_to_dup = None
        hint = f"内容近似,命中留存文章 #{art.dedup_of}"
    return {
        "id": art.id, "status": art.status, "dedup_of": art.dedup_of,
        "simhash": art.simhash, "hamming_to_dup": hamming_to_dup, "hint": hint,
    }


async def reclean(db: AsyncSession, *, article_id: int) -> None:
    art = await get_article(db, article_id=article_id)
    if art.status != CollectStatus.COLLECTED:
        raise AppError("仅 COLLECTED 态可重洗", status_code=422)
    cleaned, text = clean_html(art.raw_html)
    art.clean_html = cleaned
    sh_hex, b0, b1, b2, b3 = dedup.compute_fingerprint(text)
    art.simhash, art.simhash_b0, art.simhash_b1, art.simhash_b2, art.simhash_b3 = (
        sh_hex, b0, b1, b2, b3,
    )
    await db.commit()


async def delete_article(db: AsyncSession, *, article_id: int) -> None:
    art = await get_article(db, article_id=article_id)
    if art.status not in (CollectStatus.COLLECTED, CollectStatus.UNMATCHED):
        raise AppError("仅 COLLECTED/UNMATCHED 态可删", status_code=422)
    art.is_deleted = 1
    await db.commit()


async def stats_overview(db: AsyncSession) -> dict:
    sources_total = await db.scalar(
        select(func.count()).select_from(CollectSource).where(CollectSource.is_deleted == 0)
    )
    sources_active = await db.scalar(
        select(func.count()).select_from(CollectSource).where(
            CollectSource.is_deleted == 0, CollectSource.status == "ACTIVE"
        )
    )
    articles_total = await db.scalar(
        select(func.count()).select_from(CollectArticle).where(CollectArticle.is_deleted == 0)
    )
    rows = (
        await db.execute(
            select(CollectArticle.status, func.count())
            .where(CollectArticle.is_deleted == 0)
            .group_by(CollectArticle.status)
        )
    ).all()
    by_status = {s: c for s, c in rows}
    duplicated = await db.scalar(
        select(func.count()).select_from(CollectArticle).where(
            CollectArticle.is_deleted == 0, CollectArticle.dedup_of.is_not(None)
        )
    )
    total = articles_total or 0
    dedup_rate = round((duplicated or 0) / total * 100, 2) if total else 0.0
    return {
        "sources_total": sources_total or 0,
        "sources_active": sources_active or 0,
        "articles_total": total,
        "collected_today": by_status.get(CollectStatus.COLLECTED, 0),
        "duplicated": duplicated or 0,
        "dedup_rate": dedup_rate,
        "by_status": by_status,
    }
