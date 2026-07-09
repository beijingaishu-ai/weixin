"""wx-gateway 门面直接单测(不出网、不建 DB)。v1.1:发布走浏览器模拟。

构造 account_type=3 的 MpAccount(纯内存对象即可,Mock 路径不查库、不取 token),
以 WxGateway(redis=None) 走通:
  upload_image / add_permanent_material(素材,content-center 提审复用)
  publish(浏览器模拟建稿+发表,一步)/ takedown(下架)
再用 mock_channel.set_mock_outcome 注入失败分支:
  publish_status=3/4 → publish() 返回 FAILED(无 article_url);
  submit_errcode=48001 → publish() 在 PUBLISH 步失败,返回 FAILED(errcode=48001)。
每个测试后 reset_mock_outcomes()。

redis=None 安全:is_mock() 在 _token() 前短路,模拟号永不触碰 TokenStore。
"""
import pytest

from app.models.mp_account import MpAccount
from app.modules.wx_gateway import mock_channel
from app.modules.wx_gateway.gateway import WxGateway

MOCK_APP_ID = "wxMOCKGATEWAY00001"


def _mock_account(app_id: str = MOCK_APP_ID) -> MpAccount:
    return MpAccount(
        id=9001, mp_name="门面单测模拟号", app_id=app_id,
        app_secret_cipher=b"", key_version=1, account_type=3,
        need_review=0, created_by=1,
    )


@pytest.fixture()
def gateway() -> WxGateway:
    return WxGateway(redis=None)


@pytest.fixture(autouse=True)
def _reset_after():
    yield
    mock_channel.reset_mock_outcomes()


def test_is_mock_true_for_type_3(gateway):
    assert gateway.is_mock(_mock_account()) is True


async def test_material_roundtrip(gateway):
    """素材/正文图方法默认成功(content-center 提审管道复用)。"""
    mp = _mock_account()
    data = b"fake-image-bytes"
    img_url = await gateway.upload_image(mp, data)
    assert isinstance(img_url, str) and img_url.startswith("https://")
    mat = await gateway.add_permanent_material(mp, data)
    assert mat["media_id"] and mat["url"]


async def test_upload_image_dedup_by_content(gateway):
    mp = _mock_account()
    a = await gateway.upload_image(mp, b"same-bytes")
    b = await gateway.upload_image(mp, b"same-bytes")
    c = await gateway.upload_image(mp, b"other-bytes")
    assert a == b
    assert a != c


async def test_browser_publish_happy_path(gateway):
    """浏览器模拟发布默认成功:PUBLISHED + article_url,步骤覆盖 LOGIN..RESULT。"""
    mp = _mock_account()
    articles = [{"id": 1, "title": "T", "content": "<p>hi</p>"}]
    outcome = await gateway.publish(mp, articles)
    assert outcome.status == "PUBLISHED"
    assert outcome.ok is True
    assert outcome.article_url.startswith("https://")
    assert outcome.article_id
    phases = [s.phase for s in outcome.steps]
    for p in ("LOGIN", "NEW_DRAFT", "FILL", "UPLOAD_IMG", "SAVE", "PUBLISH", "RESULT"):
        assert p in phases


async def test_browser_takedown(gateway):
    mp = _mock_account()
    assert await gateway.takedown(mp, "https://mp.weixin.qq.com/s/MOCK_1") is True


async def test_publish_status_3_regular_failure(gateway):
    """注入 publish_status=3:发表返回常规失败,FAILED 且无 article_url。"""
    mp = _mock_account()
    mock_channel.set_mock_outcome(mp.app_id, publish_status=3)
    outcome = await gateway.publish(mp, [{"id": 1, "title": "T", "content": "<p>x</p>"}])
    assert outcome.status == "FAILED"
    assert outcome.errcode == 3
    assert not outcome.article_url


async def test_publish_status_4_audit_rejected(gateway):
    mp = _mock_account()
    mock_channel.set_mock_outcome(mp.app_id, publish_status=4)
    outcome = await gateway.publish(mp, [{"id": 1, "title": "T", "content": "<p>x</p>"}])
    assert outcome.status == "FAILED"
    assert outcome.errcode == 4


async def test_submit_errcode_48001_publish_fails(gateway):
    """注入 submit_errcode=48001:发表阶段失败,FAILED(errcode=48001)。"""
    mp = _mock_account()
    mock_channel.set_mock_outcome(mp.app_id, submit_errcode=48001)
    outcome = await gateway.publish(mp, [{"id": 1, "title": "T", "content": "<p>x</p>"}])
    assert outcome.status == "FAILED"
    assert outcome.errcode == 48001
    # PUBLISH 步失败
    pub_step = next(s for s in outcome.steps if s.phase == "PUBLISH")
    assert pub_step.ok is False


async def test_reset_mock_outcomes_restores_success(gateway):
    mp = _mock_account()
    mock_channel.set_mock_outcome(mp.app_id, publish_status=3)
    assert (await gateway.publish(mp, [{"id": 1, "title": "T", "content": "<p>x</p>"}])).status == "FAILED"
    mock_channel.reset_mock_outcomes()
    ok = await gateway.publish(mp, [{"id": 1, "title": "T", "content": "<p>x</p>"}])
    assert ok.status == "PUBLISHED"
    assert ok.article_url.startswith("https://")
