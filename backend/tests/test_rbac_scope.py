"""数据权限(RBAC scope)测试 —— operator 只见被分配公众号, 无越权。

场景(直接落库准备数据, 避免依赖尚未就绪的用户/公众号 CRUD 端点):
- 系统内共 2 个公众号 A、B;
- 建一个 operator 用户, 仅分配公众号 A(perm_level=2);
- operator 登录后:
    * GET /api/v1/mp-accounts 只返回 A(1 个), 看不到 B;
    * GET /api/v1/users 被 403(operator 无 user:manage);
    * GET /api/v1/mp-accounts/{B.id} 详情 403(未分配, 不泄露存在性);
    * GET /api/v1/mp-accounts/{A.id} 详情 200(已分配)。

数据权限唯一出口是 deps.get_visible_mp_ids + mp_account_assign, 与具体 CRUD 实现解耦,
因此即便 CRUD 端点细节仍在开发, 列表/详情的可见性契约也应稳定成立。
"""
import pytest
from sqlalchemy import select

from app.core.crypto import current_key_version, encrypt_secret
from app.core.security import hash_password
from app.models.mp_account import MpAccount, MpAccountAssign
from app.models.user import SysRole, SysUser, SysUserRole
from tests.conftest import auth_headers

pytestmark = pytest.mark.asyncio

OPERATOR_USER = "op_user"
OPERATOR_PASS = "Op@123456"


async def _seed_operator_and_accounts(session_factory):
    """建 operator 用户 + 2 个公众号(A、B), 仅把 A 分配给 operator。

    返回 (operator_id, mp_a_id, mp_b_id)。
    """
    ver = current_key_version()
    async with session_factory() as db:
        # operator 角色 id(seeds 已预置)
        op_role_id = await db.scalar(
            select(SysRole.id).where(SysRole.role_code == "operator")
        )
        assert op_role_id is not None, "seeds 应已预置 operator 角色"

        user = SysUser(
            username=OPERATOR_USER,
            password_hash=hash_password(OPERATOR_PASS),
            real_name="运营甲",
            status=1,
        )
        db.add(user)
        await db.flush()
        db.add(SysUserRole(user_id=user.id, role_id=op_role_id))

        mp_a = MpAccount(
            mp_name="公众号A",
            app_id="wxAAAAAAAAAAAAAAAA",
            app_secret_cipher=encrypt_secret("wxAAAAAAAAAAAAAAAA", "secretA0000000000000", ver),
            key_version=ver,
            account_type=1,
            created_by=1,
        )
        mp_b = MpAccount(
            mp_name="公众号B",
            app_id="wxBBBBBBBBBBBBBBBB",
            app_secret_cipher=encrypt_secret("wxBBBBBBBBBBBBBBBB", "secretB0000000000000", ver),
            key_version=ver,
            account_type=2,
            created_by=1,
        )
        db.add_all([mp_a, mp_b])
        await db.flush()

        # 仅把 A 分配给 operator
        db.add(
            MpAccountAssign(
                user_id=user.id,
                mp_account_id=mp_a.id,
                perm_level=2,
                assigned_by=1,
            )
        )
        await db.commit()
        return user.id, mp_a.id, mp_b.id


async def _login_operator(client) -> str | None:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"username": OPERATOR_USER, "password": OPERATOR_PASS},
    )
    if resp.status_code != 200:
        pytest.skip(f"登录端点未就绪: {resp.status_code} {resp.text}")
    body = resp.json()
    if body.get("code") != 0 or not body.get("data"):
        pytest.skip(f"登录响应不符合契约: {body}")
    return body["data"]["access_token"]


def _extract_items(body: dict) -> list:
    """从列表响应中取出条目数组, 兼容 data 直接为 list 或 data.items/list。"""
    data = body.get("data")
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in ("items", "list", "records", "rows"):
            if isinstance(data.get(k), list):
                return data[k]
    return []


async def test_operator_lists_only_assigned_account(client, session_factory):
    _, mp_a_id, mp_b_id = await _seed_operator_and_accounts(session_factory)
    token = await _login_operator(client)

    resp = await client.get("/api/v1/mp-accounts", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] == 0, body
    items = _extract_items(body)
    ids = {item.get("id") for item in items}
    assert mp_a_id in ids, "operator 应能看到被分配的公众号 A"
    assert mp_b_id not in ids, "operator 不应看到未分配的公众号 B"
    assert len(items) == 1, f"operator 只应看到 1 个公众号, 实得 {len(items)}"


async def test_operator_cannot_access_users(client, session_factory):
    await _seed_operator_and_accounts(session_factory)
    token = await _login_operator(client)

    resp = await client.get("/api/v1/users", headers=auth_headers(token))
    assert resp.status_code == 403, resp.text
    assert resp.json()["code"] == 403


async def test_operator_detail_unassigned_account_403(client, session_factory):
    _, _mp_a_id, mp_b_id = await _seed_operator_and_accounts(session_factory)
    token = await _login_operator(client)

    resp = await client.get(
        f"/api/v1/mp-accounts/{mp_b_id}", headers=auth_headers(token)
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["code"] == 403


async def test_operator_detail_assigned_account_ok(client, session_factory):
    _, mp_a_id, _mp_b_id = await _seed_operator_and_accounts(session_factory)
    token = await _login_operator(client)

    resp = await client.get(
        f"/api/v1/mp-accounts/{mp_a_id}", headers=auth_headers(token)
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] == 0, body
    assert body["data"]["id"] == mp_a_id
    # 详情响应绝不含明文/密文 secret 字段(零回显)
    assert "app_secret" not in body["data"]
    assert "app_secret_cipher" not in body["data"]


async def test_super_admin_sees_all_accounts(client, session_factory, admin_token):
    """对照组: 超管是 full-access 角色, 应看到全部 2 个公众号。"""
    await _seed_operator_and_accounts(session_factory)
    resp = await client.get("/api/v1/mp-accounts", headers=auth_headers(admin_token))
    assert resp.status_code == 200, resp.text
    items = _extract_items(resp.json())
    assert len(items) >= 2, "超管应可见全部公众号(至少 A、B 两个)"
