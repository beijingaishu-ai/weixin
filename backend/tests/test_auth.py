"""认证流程测试(auth_rbac router/service, 按接口契约编写)。

契约:
- POST /api/v1/auth/login {username,password} -> {code,message,data{access_token,refresh_token,user{...}}}
- GET  /api/v1/auth/me (Bearer) -> data 含角色与权限
- POST /api/v1/auth/refresh {refresh_token} -> 新 access + 新 refresh(旧 refresh 失效, 旋转)
- POST /api/v1/auth/logout (Bearer) -> 之后原 access 被拒(黑名单)

覆盖:超管登录成功、错密码失败、连续失败锁定、/auth/me 返回角色与权限、
refresh 旋转(旧 refresh 失效)、logout 后原 access 被拒。

router 未就绪时(app 不可导入)相关测试经 conftest 的 app fixture 自动 skip。
"""
import pytest

from tests.conftest import auth_headers

pytestmark = pytest.mark.asyncio

ADMIN_USER = "admin"
ADMIN_PASS = "Admin@12345"


async def test_login_success(client):
    resp = await client.post(
        "/api/v1/auth/login", json={"username": ADMIN_USER, "password": ADMIN_PASS}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] == 0, body
    data = body["data"]
    assert data["access_token"]
    assert data["refresh_token"]
    # 契约: 返回 user 概要(LoginUser{id, real_name, role, perms})
    assert "user" in data and data["user"]
    user = data["user"]
    assert user["id"]
    assert user["role"] == "super_admin", user
    assert "system:config:manage" in user["perms"], user
    # 机密红线: 登录回显绝不含密码哈希
    assert "password" not in user
    assert "password_hash" not in user


async def test_login_wrong_password_fails(client):
    resp = await client.post(
        "/api/v1/auth/login", json={"username": ADMIN_USER, "password": "wrong-password"}
    )
    # 业务失败: 非 code=0(HTTP 可为 200 带业务码或 400/401, 均视为失败)
    if resp.status_code == 200:
        assert resp.json()["code"] != 0
    else:
        assert resp.status_code in (400, 401)
    # 且不得下发令牌
    body = resp.json()
    assert not (body.get("data") or {}).get("access_token")


async def test_login_unknown_user_fails(client):
    resp = await client.post(
        "/api/v1/auth/login", json={"username": "nobody", "password": "whatever123"}
    )
    if resp.status_code == 200:
        assert resp.json()["code"] != 0
    else:
        assert resp.status_code in (400, 401)


async def test_login_lockout_after_repeated_failures(client):
    """连续错误密码达到阈值后应锁定: 即使随后给出正确密码也应被拒。

    阈值默认 LOGIN_MAX_FAIL=5(config)。锁定计数落在 FakeRedis 上。
    """
    # 触发 5 次失败
    for _ in range(5):
        await client.post(
            "/api/v1/auth/login",
            json={"username": ADMIN_USER, "password": "bad-password"},
        )
    # 第 6 次即便密码正确, 也应因锁定被拒
    resp = await client.post(
        "/api/v1/auth/login", json={"username": ADMIN_USER, "password": ADMIN_PASS}
    )
    if resp.status_code == 200:
        assert resp.json()["code"] != 0, "锁定期内正确密码不应放行"
    else:
        assert resp.status_code in (400, 401, 423, 429)


async def test_me_returns_roles_and_perms(client, admin_token):
    resp = await client.get("/api/v1/auth/me", headers=auth_headers(admin_token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] == 0, body
    data = body["data"]
    # 超管应带 super_admin 角色与非空权限集
    roles = data.get("roles") or ([data["role"]] if data.get("role") else [])
    assert "super_admin" in roles, data
    perms = data.get("perms") or data.get("permissions") or []
    assert perms, "超管应返回非空权限点集合"
    # 超管应含系统配置管理这一独有权限
    assert "system:config:manage" in perms


async def test_me_without_token_401(client):
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 401
    assert resp.json()["code"] == 401


async def test_me_with_garbage_token_401(client):
    resp = await client.get("/api/v1/auth/me", headers=auth_headers("not.a.jwt"))
    assert resp.status_code == 401


async def test_refresh_rotates_and_invalidates_old(client):
    """refresh 旋转: 用 refresh_token 换新令牌; 旧 refresh 再次使用应失败。"""
    login = await client.post(
        "/api/v1/auth/login", json={"username": ADMIN_USER, "password": ADMIN_PASS}
    )
    assert login.status_code == 200, login.text
    old_refresh = login.json()["data"]["refresh_token"]

    r1 = await client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
    assert r1.status_code == 200, r1.text
    d1 = r1.json()["data"]
    assert d1["access_token"]
    new_refresh = d1["refresh_token"]
    assert new_refresh != old_refresh, "旋转后应下发新的 refresh_token"

    # 旧 refresh 复用应被拒(已旋转失效)
    r2 = await client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
    if r2.status_code == 200:
        assert r2.json()["code"] != 0, "旧 refresh_token 复用不应成功"
    else:
        assert r2.status_code in (400, 401)


async def test_logout_blocks_old_access(client):
    """logout 后, 原 access_token 访问受保护端点应被拒(加入黑名单)。"""
    login = await client.post(
        "/api/v1/auth/login", json={"username": ADMIN_USER, "password": ADMIN_PASS}
    )
    assert login.status_code == 200, login.text
    access = login.json()["data"]["access_token"]

    # 先确认可用
    me_ok = await client.get("/api/v1/auth/me", headers=auth_headers(access))
    assert me_ok.status_code == 200

    logout = await client.post("/api/v1/auth/logout", headers=auth_headers(access))
    assert logout.status_code in (200, 204), logout.text
    if logout.status_code == 200:
        assert logout.json()["code"] == 0

    # 登出后原 access 应被拒
    me_after = await client.get("/api/v1/auth/me", headers=auth_headers(access))
    assert me_after.status_code == 401, me_after.text
    assert me_after.json()["code"] == 401
