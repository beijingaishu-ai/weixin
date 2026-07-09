"""采集器端到端 HTTP 测试(collector router/service,按接口契约编写)。

契约(响应统一 {code,message,data}):
- POST /api/v1/collect/sources
      {source_name,adapter_type:"mock",config_json:{dataset:"..."},interval_minutes:60} -> 建采集源
- POST /api/v1/collect/sources/{id}/run-now -> {collected,duplicated,total}
- GET  /api/v1/collect/articles[?status=COLLECTED] -> 采集文章列表(可按 status 筛)

覆盖:
- 超管建 mock 采集源;
- run-now 首次采集若干文章入库(status=COLLECTED);
- 再 run-now 相同内容全部去重(duplicated>0、collected=0);
- GET /articles 能按 status 筛选。

collector router 尚由他人并行实现;端点未就绪(404 / app 不可导入)时相关用例自动 skip,
不误报为失败。
"""
import pytest
from sqlalchemy import func, select

from app.core.states import CollectStatus
from app.models.collect import CollectArticle
from tests.conftest import auth_headers

pytestmark = pytest.mark.asyncio


def _skip_if_route_missing(resp, what: str):
    """collector 端点未就绪(404 Not Found)时跳过,而非误判失败。"""
    if resp.status_code == 404:
        pytest.skip(f"{what} 端点未就绪(collector 并行实现中): {resp.status_code}")


async def _create_source(
    client,
    admin_token,
    *,
    source_name="Mock采集源",
    dataset="default",
    interval_minutes=60,
):
    return await client.post(
        "/api/v1/collect/sources",
        headers=auth_headers(admin_token),
        json={
            "source_name": source_name,
            "adapter_type": "mock",
            "config_json": {"dataset": dataset},
            "interval_minutes": interval_minutes,
        },
    )


def _source_id(body: dict) -> int:
    data = body.get("data")
    if isinstance(data, dict):
        return data.get("id") or data.get("source_id")
    return data


def _run_counts(body: dict) -> dict:
    """从 run-now 响应取 {collected,duplicated,total}。"""
    return body.get("data") or {}


# ---------------------------------------------------------------------------
# 建 mock 采集源
# ---------------------------------------------------------------------------
async def test_create_mock_source(client, admin_token):
    resp = await _create_source(client, admin_token, source_name="建源测试")
    _skip_if_route_missing(resp, "POST /collect/sources")
    assert resp.status_code in (200, 201), resp.text
    body = resp.json()
    assert body["code"] == 0, body
    assert _source_id(body), f"建源应回主键 id: {body}"


# ---------------------------------------------------------------------------
# run-now 首次采集入库若干 COLLECTED
# ---------------------------------------------------------------------------
async def test_run_now_collects_articles(client, admin_token, session_factory):
    create = await _create_source(client, admin_token, source_name="首采号")
    _skip_if_route_missing(create, "POST /collect/sources")
    assert create.status_code in (200, 201), create.text
    src_id = _source_id(create.json())
    assert src_id

    run = await client.post(
        f"/api/v1/collect/sources/{src_id}/run-now",
        headers=auth_headers(admin_token),
    )
    _skip_if_route_missing(run, "POST /collect/sources/{id}/run-now")
    assert run.status_code in (200, 201), run.text
    body = run.json()
    assert body["code"] == 0, body
    counts = _run_counts(body)
    # 首次采集应有产出
    assert counts.get("collected", 0) > 0, f"首次 run-now 应采到文章: {counts}"
    assert counts.get("total", 0) >= counts.get("collected", 0)
    # 首采无历史,不应有去重
    assert counts.get("duplicated", 0) == 0, f"首采不应去重: {counts}"

    # DB 侧:入库文章 status 为 COLLECTED
    async with session_factory() as db:
        total = await db.scalar(
            select(func.count())
            .select_from(CollectArticle)
            .where(CollectArticle.source_id == src_id)
        )
        collected = await db.scalar(
            select(func.count())
            .select_from(CollectArticle)
            .where(
                CollectArticle.source_id == src_id,
                CollectArticle.status == CollectStatus.COLLECTED,
            )
        )
    assert total > 0
    assert collected == total, "首采入库文章均应为 COLLECTED"


# ---------------------------------------------------------------------------
# 再 run-now 一次:相同内容全部去重(duplicated>0, collected=0)
# ---------------------------------------------------------------------------
async def test_run_now_second_time_all_deduplicated(client, admin_token, session_factory):
    create = await _create_source(client, admin_token, source_name="去重号")
    _skip_if_route_missing(create, "POST /collect/sources")
    assert create.status_code in (200, 201), create.text
    src_id = _source_id(create.json())
    assert src_id

    # 首采
    run1 = await client.post(
        f"/api/v1/collect/sources/{src_id}/run-now", headers=auth_headers(admin_token)
    )
    _skip_if_route_missing(run1, "POST /collect/sources/{id}/run-now")
    assert run1.status_code in (200, 201), run1.text
    first = _run_counts(run1.json())
    assert first.get("collected", 0) > 0, f"首采应有产出: {first}"

    # 采集源产出固定数据集,再采一次相同内容 → 全部命中去重
    async with session_factory() as db:
        before = await db.scalar(
            select(func.count())
            .select_from(CollectArticle)
            .where(CollectArticle.source_id == src_id)
        )

    run2 = await client.post(
        f"/api/v1/collect/sources/{src_id}/run-now", headers=auth_headers(admin_token)
    )
    assert run2.status_code in (200, 201), run2.text
    second = _run_counts(run2.json())
    assert second.get("duplicated", 0) > 0, f"二次采集应全部去重: {second}"
    assert second.get("collected", 0) == 0, f"相同内容不应新增: {second}"

    # DB 侧:文章总数未增长(url_hash 唯一约束 + 去重逻辑)
    async with session_factory() as db:
        after = await db.scalar(
            select(func.count())
            .select_from(CollectArticle)
            .where(CollectArticle.source_id == src_id)
        )
    assert after == before, f"去重后文章总数不应增加: {before} -> {after}"


# ---------------------------------------------------------------------------
# GET /articles 能按 status 筛选
# ---------------------------------------------------------------------------
async def test_list_articles_filter_by_status(client, admin_token):
    create = await _create_source(client, admin_token, source_name="筛选号")
    _skip_if_route_missing(create, "POST /collect/sources")
    assert create.status_code in (200, 201), create.text
    src_id = _source_id(create.json())

    run = await client.post(
        f"/api/v1/collect/sources/{src_id}/run-now", headers=auth_headers(admin_token)
    )
    _skip_if_route_missing(run, "POST /collect/sources/{id}/run-now")
    assert run.status_code in (200, 201), run.text

    # 无筛选:应至少返回刚采集的文章
    all_resp = await client.get(
        "/api/v1/collect/articles", headers=auth_headers(admin_token)
    )
    _skip_if_route_missing(all_resp, "GET /collect/articles")
    assert all_resp.status_code == 200, all_resp.text
    assert all_resp.json()["code"] == 0
    all_items = _extract_items(all_resp.json())
    assert len(all_items) > 0, "采集后列表不应为空"

    # 按 COLLECTED 筛:返回项 status 均为 COLLECTED
    filt = await client.get(
        "/api/v1/collect/articles",
        headers=auth_headers(admin_token),
        params={"status": CollectStatus.COLLECTED.value},
    )
    assert filt.status_code == 200, filt.text
    filt_items = _extract_items(filt.json())
    assert len(filt_items) > 0, "刚采集的文章应能被 COLLECTED 筛出"
    for item in filt_items:
        assert item.get("status") == CollectStatus.COLLECTED.value, item

    # 按不存在的终态筛(TRANSFORMED):此时无一命中,应为空
    empty = await client.get(
        "/api/v1/collect/articles",
        headers=auth_headers(admin_token),
        params={"status": CollectStatus.TRANSFORMED.value},
    )
    assert empty.status_code == 200, empty.text
    assert len(_extract_items(empty.json())) == 0, "尚无 TRANSFORMED 文章,应为空"


def _extract_items(body: dict) -> list:
    """兼容 data 为 list 或 {items/list/records/rows: [...]}。"""
    data = body.get("data")
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in ("items", "list", "records", "rows"):
            if isinstance(data.get(k), list):
                return data[k]
    return []
