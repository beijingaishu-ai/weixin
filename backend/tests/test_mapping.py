"""M3 映射引擎测试:端到端(采集→映射→产出/原创拦截)+ matcher 单测。"""
from types import SimpleNamespace

import pytest

from app.modules.mapping_engine import matcher
from tests.conftest import auth_headers


def _art(title="", content=""):
    return SimpleNamespace(title=title, clean_html=content)


# ---------------------------------------------------------------------------
# matcher 纯函数单测(无需 DB)
# ---------------------------------------------------------------------------
def test_matcher_exclude_veto():
    cond = {"keywords_include": ["AI"], "keywords_exclude": ["广告"]}
    assert matcher.evaluate(cond, _art("AI 大模型深度", "正文")) is True
    # 排除词一票否决,优先于包含词
    assert matcher.evaluate(cond, _art("AI 广告推广", "正文")) is False


def test_matcher_include_any_all():
    art = _art("新能源电池技术", "储能与快充")
    assert matcher.evaluate({"keywords_include": ["电池", "光伏"], "keywords_include_mode": "ANY"}, art) is True
    assert matcher.evaluate({"keywords_include": ["电池", "光伏"], "keywords_include_mode": "ALL"}, art) is False
    assert matcher.evaluate({"keywords_include": ["电池", "储能"], "keywords_include_mode": "ALL", "match_field": "title_and_content"}, art) is True


def test_matcher_min_word_count():
    art = _art("短讯", "只有几个字")
    assert matcher.evaluate({"min_word_count": 100}, art) is False
    assert matcher.evaluate({"min_word_count": 3}, art) is True


def test_matcher_empty_matches_all():
    assert matcher.evaluate({}, _art("任意标题", "任意正文")) is True
    assert matcher.evaluate(None, _art("x", "y")) is True


# ---------------------------------------------------------------------------
# 端到端:采集 → 映射
# ---------------------------------------------------------------------------
async def _create_mock_mp(client, token, app_id="wxmap0001"):
    resp = await client.post(
        "/api/v1/mp-accounts",
        headers=auth_headers(token),
        json={"mp_name": "映射目标号", "account_type": 3, "app_id": app_id, "app_secret": "MOCK"},
    )
    body = resp.json()
    assert body["code"] == 0, body
    return body["data"]["id"]


async def _create_source(client, token, *, dataset="tech", whitelist=0, name="科技源"):
    resp = await client.post(
        "/api/v1/collect/sources",
        headers=auth_headers(token),
        json={
            "source_name": name, "adapter_type": "mock",
            "config_json": {"dataset": dataset},
            "interval_minutes": 60, "whitelist_confirmed": whitelist,
        },
    )
    body = resp.json()
    assert body["code"] == 0, body
    return body["data"]["id"]


async def _articles(client, token, source_id):
    resp = await client.get(
        f"/api/v1/collect/articles?source_id={source_id}&page_size=100",
        headers=auth_headers(token),
    )
    return resp.json()["data"]["items"]


@pytest.mark.asyncio
async def test_collect_map_and_original_block(client, admin_token):
    token = admin_token
    mp_id = await _create_mock_mp(client, token)
    src_id = await _create_source(client, token, dataset="tech", whitelist=0)

    # 采集 tech 数据集(5 篇,其中 1 篇 is_original_marked)
    run = (await client.post(
        f"/api/v1/collect/sources/{src_id}/run-now", headers=auth_headers(token)
    )).json()["data"]
    assert run["collected"] == 5, run

    # 建映射规则:该源 → 目标号,无筛选(match all),标题加【转】前缀 + 来源声明
    rule_resp = await client.post(
        "/api/v1/mapping/rules",
        headers=auth_headers(token),
        json={
            "rule_name": "科技源转载",
            "target_mp_account_id": mp_id,
            "source_ids": [src_id],
            "match_condition_json": {},
            "transform_action_json": {
                "title_template": "【转】{title}",
                "body_pipeline": [
                    {"type": "append_block", "position": "tail",
                     "template": "<hr/><p>本文转载自{source_name}</p>"}
                ],
            },
            "schedule_policy_json": {},
            "priority": 100,
        },
    )
    assert rule_resp.json()["code"] == 0, rule_resp.json()

    # 处理待映射
    rp = (await client.post(
        "/api/v1/mapping/run-pending", headers=auth_headers(token)
    )).json()["data"]
    assert rp["processed"] == 5, rp
    # 4 篇非原创命中转换,1 篇原创被拦截
    assert rp["transformed"] == 4, rp
    assert rp["unmatched"] == 1, rp
    assert rp["produced_content"] == 4, rp

    # 校验采集文章状态
    arts = await _articles(client, token, src_id)
    by_status: dict[str, int] = {}
    original = None
    for a in arts:
        by_status[a["status"]] = by_status.get(a["status"], 0) + 1
        if a["is_original_marked"] == 1:
            original = a
    assert by_status.get("TRANSFORMED") == 4, by_status
    assert by_status.get("UNMATCHED") == 1, by_status
    # 原创文章被拦截,原因含"原创"
    assert original is not None and original["status"] == "UNMATCHED"
    assert "原创" in original["unmatched_reason"], original

    # 校验产出的 content_article:标题带【转】前缀,状态 TRANSFORMED
    arts_resp = await client.get(
        f"/api/v1/articles?mp_account_id={mp_id}&page_size=100", headers=auth_headers(token)
    )
    items = arts_resp.json()["data"]["items"]
    assert len(items) == 4, items
    assert all(it["status"] == "TRANSFORMED" for it in items), items
    assert all(it["title"].startswith("【转】") for it in items), [it["title"] for it in items]


@pytest.mark.asyncio
async def test_original_allowed_when_whitelist_confirmed(client, admin_token):
    """源已确认授权(whitelist_confirmed=1)时,原创文章不再被拦截。"""
    token = admin_token
    mp_id = await _create_mock_mp(client, token, app_id="wxmap0002")
    src_id = await _create_source(client, token, dataset="tech", whitelist=1, name="已授权源")

    await client.post(f"/api/v1/collect/sources/{src_id}/run-now", headers=auth_headers(token))
    await client.post(
        "/api/v1/mapping/rules",
        headers=auth_headers(token),
        json={
            "rule_name": "已授权转载", "target_mp_account_id": mp_id, "source_ids": [src_id],
            "match_condition_json": {}, "transform_action_json": {"title_template": "{title}"},
            "schedule_policy_json": {}, "priority": 100,
        },
    )
    rp = (await client.post(
        "/api/v1/mapping/run-pending", headers=auth_headers(token)
    )).json()["data"]
    # 5 篇全部命中(含原创,因已授权)
    assert rp["transformed"] == 5, rp
    assert rp["unmatched"] == 0, rp


@pytest.mark.asyncio
async def test_no_rule_match_unmatched(client, admin_token):
    """规则不命中的文章 → UNMATCHED。"""
    token = admin_token
    mp_id = await _create_mock_mp(client, token, app_id="wxmap0003")
    src_id = await _create_source(client, token, dataset="tech", whitelist=1, name="无命中源")
    await client.post(f"/api/v1/collect/sources/{src_id}/run-now", headers=auth_headers(token))
    await client.post(
        "/api/v1/mapping/rules",
        headers=auth_headers(token),
        json={
            "rule_name": "永不命中", "target_mp_account_id": mp_id, "source_ids": [src_id],
            "match_condition_json": {"keywords_include": ["绝对不存在的关键词ZZZ"]},
            "transform_action_json": {}, "schedule_policy_json": {}, "priority": 100,
        },
    )
    rp = (await client.post(
        "/api/v1/mapping/run-pending", headers=auth_headers(token)
    )).json()["data"]
    assert rp["transformed"] == 0, rp
    assert rp["unmatched"] == 5, rp
