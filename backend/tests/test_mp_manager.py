"""公众号管理测试(mp_manager router/service, 按接口契约编写)。

契约:
- POST /api/v1/mp-accounts {mp_name,account_type,app_id,app_secret,...} -> 建号, 响应不含 secret
- GET  /api/v1/mp-accounts / GET /api/v1/mp-accounts/{id} -> 列表/详情均不含 secret(零回显)
- PUT  /api/v1/mp-accounts/{id}/assignees {assignments:[{user_id,perm_level}]} -> 覆盖式分配(add/remove/change diff)
- GET  /api/v1/internal/mp-accounts/{app_id}/credential (Header X-Internal-Token)
       正确 token -> 返回明文 app_secret; 错 token -> 401

覆盖:建号后列表/详情不含 secret; 内部凭据接口正确 token 返回明文、错 token 401;
分配 add/remove/change diff 正确。
"""
import pytest
from sqlalchemy import select

from app.core.crypto import current_key_version, encrypt_secret
from app.core.security import hash_password
from app.models.mp_account import MpAccount, MpAccountAssign
from app.models.user import SysRole, SysUser, SysUserRole
from tests.conftest import auth_headers

pytestmark = pytest.mark.asyncio

APP_ID = "wxCREATE0000000000"
APP_SECRET = "creation-secret-abcdef1234567890"
INTERNAL_TOKEN = "test-internal"  # 与 conftest 设置的 INTERNAL_TOKEN 一致


# ---------------------------------------------------------------------------
# 直接落库辅助(用于内部凭据接口 / 分配 diff 的数据准备)
# ---------------------------------------------------------------------------
async def _seed_account(session_factory, app_id: str, secret: str, name: str = "号") -> int:
    ver = current_key_version()
    async with session_factory() as db:
        acc = MpAccount(
            mp_name=name,
            app_id=app_id,
            app_secret_cipher=encrypt_secret(app_id, secret, ver),
            key_version=ver,
            account_type=1,
            created_by=1,
        )
        db.add(acc)
        await db.commit()
        return acc.id


async def _seed_operator(session_factory, username: str) -> int:
    async with session_factory() as db:
        op_role_id = await db.scalar(
            select(SysRole.id).where(SysRole.role_code == "operator")
        )
        user = SysUser(
            username=username,
            password_hash=hash_password("Op@123456"),
            real_name=username,
            status=1,
        )
        db.add(user)
        await db.flush()
        db.add(SysUserRole(user_id=user.id, role_id=op_role_id))
        await db.commit()
        return user.id


async def _active_assignments(session_factory, mp_id: int) -> dict[int, int]:
    """返回该公众号当前有效分配: {user_id: perm_level}(deleted_flag=0)。"""
    async with session_factory() as db:
        rows = await db.execute(
            select(MpAccountAssign.user_id, MpAccountAssign.perm_level).where(
                MpAccountAssign.mp_account_id == mp_id,
                MpAccountAssign.deleted_flag == 0,
            )
        )
        return {uid: lvl for uid, lvl in rows.all()}


# ---------------------------------------------------------------------------
# 建号 & 零回显
# ---------------------------------------------------------------------------
async def test_create_account_response_has_no_secret(client, admin_token):
    resp = await client.post(
        "/api/v1/mp-accounts",
        headers=auth_headers(admin_token),
        json={
            "mp_name": "新建公众号",
            "account_type": 1,
            "app_id": APP_ID,
            "app_secret": APP_SECRET,
        },
    )
    assert resp.status_code in (200, 201), resp.text
    body = resp.json()
    assert body["code"] == 0, body
    data = body["data"]
    # 契约(MpCreateResult): 建号仅回主键 id
    assert data.get("id")
    # 零回显: 响应不得含明文或密文 secret
    assert "app_secret" not in data
    assert "app_secret_cipher" not in data


async def test_list_and_detail_exclude_secret(client, admin_token):
    create = await client.post(
        "/api/v1/mp-accounts",
        headers=auth_headers(admin_token),
        json={
            "mp_name": "零回显校验号",
            "account_type": 1,
            "app_id": "wxNOSECRET00000000",
            "app_secret": "should-never-echo-secret",
        },
    )
    assert create.status_code in (200, 201), create.text
    mp_id = create.json()["data"]["id"]

    # 列表
    lst = await client.get("/api/v1/mp-accounts", headers=auth_headers(admin_token))
    assert lst.status_code == 200
    for item in _extract_items(lst.json()):
        assert "app_secret" not in item
        assert "app_secret_cipher" not in item

    # 详情
    detail = await client.get(
        f"/api/v1/mp-accounts/{mp_id}", headers=auth_headers(admin_token)
    )
    assert detail.status_code == 200, detail.text
    d = detail.json()["data"]
    assert "app_secret" not in d
    assert "app_secret_cipher" not in d


def _extract_items(body: dict) -> list:
    data = body.get("data")
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in ("items", "list", "records", "rows"):
            if isinstance(data.get(k), list):
                return data[k]
    return []


# ---------------------------------------------------------------------------
# 内部凭据接口(wx-gateway 用): 正确 token 明文回, 错 token 401
# ---------------------------------------------------------------------------
async def test_internal_credential_correct_token_returns_plaintext(client, session_factory):
    await _seed_account(session_factory, APP_ID, APP_SECRET, name="凭据号")
    resp = await client.get(
        f"/api/v1/internal/mp-accounts/{APP_ID}/credential",
        headers={"X-Internal-Token": INTERNAL_TOKEN},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] == 0, body
    data = body["data"]
    assert data["app_id"] == APP_ID
    # 内部接口是唯一允许回明文 secret 的出口
    assert data["app_secret"] == APP_SECRET


async def test_internal_credential_wrong_token_401(client, session_factory):
    await _seed_account(session_factory, APP_ID, APP_SECRET, name="凭据号")
    resp = await client.get(
        f"/api/v1/internal/mp-accounts/{APP_ID}/credential",
        headers={"X-Internal-Token": "wrong-token"},
    )
    assert resp.status_code == 401, resp.text
    assert resp.json()["code"] == 401


async def test_internal_credential_missing_token_401(client, session_factory):
    await _seed_account(session_factory, APP_ID, APP_SECRET, name="凭据号")
    resp = await client.get(
        f"/api/v1/internal/mp-accounts/{APP_ID}/credential"
    )
    assert resp.status_code == 401, resp.text


# ---------------------------------------------------------------------------
# 分配 diff: add / remove / change
# ---------------------------------------------------------------------------
async def test_assign_add_remove_change_diff(client, session_factory, admin_token):
    """覆盖式分配的三种 diff:

    初态: 号 X 分配给 u1(级 2)、u2(级 2)。
    PUT 覆盖为: u1(级 4, change)、u3(级 3, add), 去掉 u2(remove)。
    期望有效分配: {u1:4, u3:3}, u2 不再有效。
    """
    mp_id = await _seed_account(session_factory, "wxASSIGN0000000000", "assign-secret-000000")
    u1 = await _seed_operator(session_factory, "assignee1")
    u2 = await _seed_operator(session_factory, "assignee2")
    u3 = await _seed_operator(session_factory, "assignee3")

    # 初始分配 u1、u2(perm_level=2)
    init = await client.put(
        f"/api/v1/mp-accounts/{mp_id}/assignees",
        headers=auth_headers(admin_token),
        json={"assignments": [
            {"user_id": u1, "perm_level": 2},
            {"user_id": u2, "perm_level": 2},
        ]},
    )
    assert init.status_code == 200, init.text
    assert init.json()["code"] == 0
    after_init = await _active_assignments(session_factory, mp_id)
    assert after_init == {u1: 2, u2: 2}, after_init

    # 覆盖: u1->4(change), u3->3(add), 移除 u2(remove)
    upd = await client.put(
        f"/api/v1/mp-accounts/{mp_id}/assignees",
        headers=auth_headers(admin_token),
        json={"assignments": [
            {"user_id": u1, "perm_level": 4},
            {"user_id": u3, "perm_level": 3},
        ]},
    )
    assert upd.status_code == 200, upd.text
    assert upd.json()["code"] == 0

    final = await _active_assignments(session_factory, mp_id)
    assert final == {u1: 4, u3: 3}, f"diff 结果不符: {final}"
    assert u2 not in final, "被移除的 u2 不应仍有效"


async def test_assign_empty_clears_all(client, session_factory, admin_token):
    """PUT 空列表应清空全部有效分配(全 remove)。"""
    mp_id = await _seed_account(session_factory, "wxCLEAR00000000000", "clear-secret-0000000")
    u1 = await _seed_operator(session_factory, "clr_u1")

    await client.put(
        f"/api/v1/mp-accounts/{mp_id}/assignees",
        headers=auth_headers(admin_token),
        json={"assignments": [{"user_id": u1, "perm_level": 2}]},
    )
    assert (await _active_assignments(session_factory, mp_id)) == {u1: 2}

    cleared = await client.put(
        f"/api/v1/mp-accounts/{mp_id}/assignees",
        headers=auth_headers(admin_token),
        json={"assignments": []},
    )
    assert cleared.status_code == 200, cleared.text
    assert (await _active_assignments(session_factory, mp_id)) == {}


async def test_create_account_persists_encrypted_secret(client, session_factory, admin_token):
    """建号后 DB 落的是密文, 且可被内部接口以明文取回(端到端 secret 生命周期)。"""
    app_id = "wxE2ESECRET000000"
    secret = "end-to-end-secret-value-123456"
    create = await client.post(
        "/api/v1/mp-accounts",
        headers=auth_headers(admin_token),
        json={"mp_name": "端到端号", "account_type": 1, "app_id": app_id, "app_secret": secret},
    )
    assert create.status_code in (200, 201), create.text

    # DB 中存的必须是密文(不等于明文, 且非空 bytes)
    async with session_factory() as db:
        cipher = await db.scalar(
            select(MpAccount.app_secret_cipher).where(MpAccount.app_id == app_id)
        )
    assert cipher is not None and isinstance(cipher, (bytes, bytearray))
    assert bytes(cipher) != secret.encode("utf-8")

    # 内部接口取回明文
    got = await client.get(
        f"/api/v1/internal/mp-accounts/{app_id}/credential",
        headers={"X-Internal-Token": INTERNAL_TOKEN},
    )
    assert got.status_code == 200, got.text
    assert got.json()["data"]["app_secret"] == secret
