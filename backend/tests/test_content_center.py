"""内容中心端到端 HTTP 测试(content_center router/service,按接口契约编写)。

契约(响应统一 {code,message,data}):
- POST /api/v1/materials        multipart files={"file":(name,bytes,ctype)} -> 素材落库(SHA-256 去重)
- POST /api/v1/articles         {mp_account_id,title,content_html,cover_material_id?} -> 建图文(TRANSFORMED)
- POST /api/v1/articles/{id}/submit                                                   -> 提审
- POST /api/v1/articles/{id}/audit {result:"pass"|"reject",opinion?}                  -> 审核

覆盖:
- 素材同内容二次上传去重(file_hash 一致、id 相同);
- 建图文初始 TRANSFORMED;提审(need_review 默认开)→ PENDING_REVIEW;审核 pass → APPROVED;
- html_pipeline 白名单:提交含 <script> 的正文,保存后被清除。

content_center router 尚由他人并行实现;端点未就绪(404 / app 不可导入)时相关用例自动 skip,
不误报为失败。建 Mock 号统一用 account_type=3,直接 ORM 落库(共享内存引擎)。
"""
import pytest
from sqlalchemy import select

from app.core.crypto import current_key_version, encrypt_secret
from app.models.content import ContentArticle, ContentMaterial
from app.models.mp_account import MpAccount
from tests.conftest import auth_headers

pytestmark = pytest.mark.asyncio

_IMG_BYTES = b"\xff\xd8\xff\xe0hello-jpeg-bytes-content-center"


# ---------------------------------------------------------------------------
# 辅助:直接落库建一个 account_type=3 的 Mock 公众号(需要 need_review 时可指定)
# ---------------------------------------------------------------------------
async def _seed_mock_account(
    session_factory, app_id: str, *, need_review: int = 1, name: str = "内容中心Mock号"
) -> int:
    ver = current_key_version()
    async with session_factory() as db:
        acc = MpAccount(
            mp_name=name,
            app_id=app_id,
            app_secret_cipher=encrypt_secret(app_id, "cc-mock-secret-000000", ver),
            key_version=ver,
            account_type=3,       # 走 MockChannel
            need_review=need_review,
            created_by=1,
        )
        db.add(acc)
        await db.commit()
        return acc.id


def _skip_if_route_missing(resp, what: str):
    """content_center 端点未就绪(404 Not Found)时跳过,而非误判失败。"""
    if resp.status_code == 404:
        pytest.skip(f"{what} 端点未就绪(content_center 并行实现中): {resp.status_code}")


async def _upload_material(client, admin_token, data: bytes, filename="cover.jpg", ctype="image/jpeg"):
    return await client.post(
        "/api/v1/materials",
        headers=auth_headers(admin_token),
        files={"file": (filename, data, ctype)},
    )


def _material_id(body: dict) -> int:
    """从素材上传响应里取出素材 id(兼容 data 为对象或直接为 id)。"""
    data = body.get("data")
    if isinstance(data, dict):
        return data.get("id") or data.get("material_id")
    return data


def _article_status(body: dict) -> str:
    data = body.get("data") or {}
    return data.get("status") if isinstance(data, dict) else None


# ---------------------------------------------------------------------------
# 素材上传去重:同内容二次上传 file_hash 一致、id 相同
# ---------------------------------------------------------------------------
async def test_material_upload_dedup(client, admin_token, session_factory):
    first = await _upload_material(client, admin_token, _IMG_BYTES)
    _skip_if_route_missing(first, "POST /materials")
    assert first.status_code in (200, 201), first.text
    assert first.json()["code"] == 0, first.text
    id1 = _material_id(first.json())
    assert id1

    # 同内容二次上传:秒传去重 —— 返回同一 id
    second = await _upload_material(client, admin_token, _IMG_BYTES, filename="another-name.jpg")
    assert second.status_code in (200, 201), second.text
    assert second.json()["code"] == 0
    id2 = _material_id(second.json())
    assert id2 == id1, f"同内容应去重复用同一素材 id: {id1} != {id2}"

    # DB 侧:该内容仅一行 content_material,file_hash 落的是 SHA-256
    async with session_factory() as db:
        rows = (
            await db.execute(select(ContentMaterial).where(ContentMaterial.id == id1))
        ).scalars().all()
    assert len(rows) == 1
    import hashlib

    assert rows[0].file_hash == hashlib.sha256(_IMG_BYTES).hexdigest()


# ---------------------------------------------------------------------------
# 建图文:初始态 TRANSFORMED
# ---------------------------------------------------------------------------
async def test_create_article_initial_transformed(client, admin_token, session_factory):
    mp_id = await _seed_mock_account(session_factory, "wxCCARTICLE0000001")
    resp = await client.post(
        "/api/v1/articles",
        headers=auth_headers(admin_token),
        json={
            "mp_account_id": mp_id,
            "title": "首篇图文",
            "content_html": "<p>正文内容</p>",
        },
    )
    _skip_if_route_missing(resp, "POST /articles")
    assert resp.status_code in (200, 201), resp.text
    body = resp.json()
    assert body["code"] == 0, body
    art_id = (body["data"] or {}).get("id")
    assert art_id

    async with session_factory() as db:
        status = await db.scalar(
            select(ContentArticle.status).where(ContentArticle.id == art_id)
        )
    assert status == "TRANSFORMED", f"新建图文初始应为 TRANSFORMED, 实为 {status}"


# ---------------------------------------------------------------------------
# 提审 → PENDING_REVIEW；审核 pass → APPROVED
# ---------------------------------------------------------------------------
async def test_submit_then_audit_pass(client, admin_token, session_factory):
    mp_id = await _seed_mock_account(
        session_factory, "wxCCAUDIT00000001", need_review=1
    )
    create = await client.post(
        "/api/v1/articles",
        headers=auth_headers(admin_token),
        json={
            "mp_account_id": mp_id,
            "title": "待审图文",
            "content_html": "<p>需要走审核</p>",
        },
    )
    _skip_if_route_missing(create, "POST /articles")
    assert create.status_code in (200, 201), create.text
    art_id = (create.json()["data"] or {}).get("id")
    assert art_id

    # 提审:need_review 开 → PENDING_REVIEW
    submit = await client.post(
        f"/api/v1/articles/{art_id}/submit", headers=auth_headers(admin_token)
    )
    _skip_if_route_missing(submit, "POST /articles/{id}/submit")
    assert submit.status_code in (200, 201), submit.text
    assert submit.json()["code"] == 0, submit.text

    async with session_factory() as db:
        st = await db.scalar(
            select(ContentArticle.status).where(ContentArticle.id == art_id)
        )
    assert st == "PENDING_REVIEW", f"need_review 开时提审应为 PENDING_REVIEW, 实为 {st}"

    # 审核 pass → APPROVED
    audit = await client.post(
        f"/api/v1/articles/{art_id}/audit",
        headers=auth_headers(admin_token),
        json={"result": "pass", "opinion": "内容合规"},
    )
    _skip_if_route_missing(audit, "POST /articles/{id}/audit")
    assert audit.status_code in (200, 201), audit.text
    assert audit.json()["code"] == 0, audit.text

    async with session_factory() as db:
        st2 = await db.scalar(
            select(ContentArticle.status).where(ContentArticle.id == art_id)
        )
    assert st2 == "APPROVED", f"审核 pass 后应为 APPROVED, 实为 {st2}"


# ---------------------------------------------------------------------------
# 审核 reject → REJECTED
# ---------------------------------------------------------------------------
async def test_audit_reject(client, admin_token, session_factory):
    mp_id = await _seed_mock_account(
        session_factory, "wxCCREJECT0000001", need_review=1
    )
    create = await client.post(
        "/api/v1/articles",
        headers=auth_headers(admin_token),
        json={"mp_account_id": mp_id, "title": "被驳回图文", "content_html": "<p>x</p>"},
    )
    _skip_if_route_missing(create, "POST /articles")
    assert create.status_code in (200, 201), create.text
    art_id = (create.json()["data"] or {}).get("id")

    submit = await client.post(
        f"/api/v1/articles/{art_id}/submit", headers=auth_headers(admin_token)
    )
    _skip_if_route_missing(submit, "POST /articles/{id}/submit")
    assert submit.status_code in (200, 201), submit.text

    audit = await client.post(
        f"/api/v1/articles/{art_id}/audit",
        headers=auth_headers(admin_token),
        json={"result": "reject", "opinion": "含违规表述"},
    )
    _skip_if_route_missing(audit, "POST /articles/{id}/audit")
    assert audit.status_code in (200, 201), audit.text
    assert audit.json()["code"] == 0, audit.text

    async with session_factory() as db:
        st = await db.scalar(
            select(ContentArticle.status).where(ContentArticle.id == art_id)
        )
    assert st == "REJECTED", f"审核 reject 后应为 REJECTED, 实为 {st}"


# ---------------------------------------------------------------------------
# html_pipeline 白名单:含 <script> 的正文保存后被清除
# ---------------------------------------------------------------------------
async def test_html_pipeline_strips_script(client, admin_token, session_factory):
    mp_id = await _seed_mock_account(session_factory, "wxCCXSS000000001")
    dangerous = (
        "<p>正常段落</p>"
        "<script>alert('xss')</script>"
        "<p>结尾</p>"
    )
    resp = await client.post(
        "/api/v1/articles",
        headers=auth_headers(admin_token),
        json={
            "mp_account_id": mp_id,
            "title": "含脚本图文",
            "content_html": dangerous,
        },
    )
    _skip_if_route_missing(resp, "POST /articles")
    assert resp.status_code in (200, 201), resp.text
    art_id = (resp.json()["data"] or {}).get("id")
    assert art_id

    async with session_factory() as db:
        saved_html = await db.scalar(
            select(ContentArticle.content_html).where(ContentArticle.id == art_id)
        )
    assert saved_html is not None
    low = saved_html.lower()
    assert "<script" not in low, f"白名单应清除 <script>, 实存: {saved_html!r}"
    assert "alert(" not in low, f"脚本内容不应残留: {saved_html!r}"
    # 正常段落应保留
    assert "正常段落" in saved_html
