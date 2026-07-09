"""采集去重(对齐设计 5.7)。

两道闸(URL 精确 + SimHash 近似):
- 闸1 URL 精确:url_hash 命中已存在文章 → dup_kind="url"。因 url_hash 有唯一约束,
  URL 完全相同者无法二次入库,故直接跳过不插入。
- 闸3 SimHash 近似:URL 不同但正文相似(Hamming≤3)→ dup_kind="content"。
  这类**入库但置 UNMATCHED + dedup_of**,便于教学复盘与误判排查。

标题相似(闸2)作为可选预判,这里并入 SimHash 一并处理,不单独建阈值。
"""
from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import simhash as sh
from app.models.collect import CollectArticle

HAMMING_THRESHOLD = 3


def compute_fingerprint(clean_text: str) -> tuple[str, int, int, int, int]:
    """返回 (simhash_hex, b0, b1, b2, b3),供入库填充。"""
    value = sh.simhash64(clean_text)
    b0, b1, b2, b3 = sh.bands(value)
    return sh.simhash_hex(value), b0, b1, b2, b3


async def dedup_check(
    db: AsyncSession, *, url: str, title: str, clean_text: str
) -> tuple[str | None, int | None]:
    """返回 (dup_kind, dedup_of)。dup_kind ∈ {None, 'url', 'content'}。"""
    fallback = sh.normalize_title(title) + clean_text[:200]
    uh = sh.url_hash(url, fallback=fallback)

    # 闸1:URL 精确
    hit = await db.scalar(
        select(CollectArticle.id).where(
            CollectArticle.url_hash == uh, CollectArticle.is_deleted == 0
        )
    )
    if hit is not None:
        return "url", hit

    # 闸3:SimHash 近似(任一段相等召回候选,再精确 Hamming 比对)
    value = sh.simhash64(clean_text)
    b0, b1, b2, b3 = sh.bands(value)
    rows = (
        await db.execute(
            select(CollectArticle.id, CollectArticle.simhash).where(
                CollectArticle.is_deleted == 0,
                or_(
                    CollectArticle.simhash_b0 == b0,
                    CollectArticle.simhash_b1 == b1,
                    CollectArticle.simhash_b2 == b2,
                    CollectArticle.simhash_b3 == b3,
                ),
            ).limit(200)
        )
    ).all()
    for cid, cand_hex in rows:
        try:
            cand_val = int(cand_hex, 16)
        except (ValueError, TypeError):
            continue
        if sh.hamming(value, cand_val) <= HAMMING_THRESHOLD:
            return "content", cid

    return None, None
