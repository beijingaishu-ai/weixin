"""公众号后台登录态捕获(浏览器发布前置,一次扫码长期复用)。

用法(在你自己的机器上,装好 playwright 后):
    cd backend
    .venv/Scripts/python -m playwright install chromium   # 首次装浏览器内核
    .venv/Scripts/python scripts/wx_login.py wx你的AppID

流程:
  1. 弹出有头 Chromium,打开 mp.weixin.qq.com;
  2. 你用**该公众号管理员微信**扫码登录;
  3. 登录成功(URL 出现 token=...)后,脚本把登录态存到
     secrets/wx_state/<app_id>.json,并退出。

该文件等同账号凭据:已被 .gitignore 忽略(secrets/),请勿外传;失效后重新跑本脚本即可。
登录态通常可用数天到数周,过期后 BrowserChannel 会报"未登录",届时重跑本脚本。
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# 允许脚本直接运行时找到 app 包
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402

WX_HOME = "https://mp.weixin.qq.com"


async def persist_login(app_id: str) -> None:
    """扫码成功(已进入后台,token 出现)后回写 mp_account 登录态授权。

    置 AUTHORIZED + wx_login_expires_at = now + ttl(行级 wx_login_ttl_hours 优先,否则全局
    WX_LOGIN_TTL_HOURS),清 alerted_at。这是「2 天有效期窗口」生效的根子:窗口内 headless
    发布复用同一份 storage_state 全自动发文。DB 无此号则仅提示(仍已存登录态文件)。
    """
    from datetime import datetime, timedelta

    from sqlalchemy import select

    from app.core.db import SessionLocal
    from app.core.states import IllegalTransition, WxLoginStatus, ensure_transition
    from app.models.mp_account import MpAccount

    async with SessionLocal() as db:
        mp = await db.scalar(
            select(MpAccount).where(MpAccount.app_id == app_id, MpAccount.is_deleted == 0)
        )
        if mp is None:
            print(f"提示:DB 未找到 app_id={app_id} 的公众号,已存登录态文件但未回写有效期。")
            return
        ttl = mp.wx_login_ttl_hours or settings.WX_LOGIN_TTL_HOURS
        now = datetime.utcnow()
        try:
            ensure_transition("mp_account_login", mp.wx_login_status, WxLoginStatus.AUTHORIZED)
        except IllegalTransition:
            pass  # 任意态 → AUTHORIZED 均在白名单;兜底忽略
        mp.wx_login_status = WxLoginStatus.AUTHORIZED
        mp.wx_login_captured_at = now
        mp.wx_login_expires_at = now + timedelta(hours=ttl)
        mp.wx_login_alerted_at = None
        await db.commit()
        print(f"已回写登录态授权:「{mp.mp_name}」有效期至 {mp.wx_login_expires_at} (UTC, +{ttl}h)")


async def capture(app_id: str) -> None:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("未安装 playwright。请先: pip install playwright && python -m playwright install chromium")
        sys.exit(1)

    out_dir = Path(settings.WX_STORAGE_STATE_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{app_id}.json"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)  # 登录必须有头以便扫码
        ctx = await browser.new_context()
        page = await ctx.new_page()
        await page.goto(WX_HOME)

        # 后台自动轮询检测登录(URL 出现 token 即视为已登录),最多 300 秒;
        # 同时支持:登录后回到终端按 Enter 立即保存(最稳,不依赖 URL 判定)。
        print("\n请用该公众号【管理员微信】扫码登录。")
        print("登录进入后台首页后,回到本终端【按 Enter】保存登录态(或等脚本自动检测)。\n")

        loop = asyncio.get_event_loop()
        enter_task = loop.run_in_executor(None, input)  # 等用户按 Enter

        detected = False
        for _ in range(150):  # 150 * 2s = 300s
            if enter_task.done():
                break
            if "token=" in page.url:
                detected = True
                break
            await asyncio.sleep(2)

        logged_in = detected or ("token=" in page.url)
        if not logged_in:
            print(f"提示:当前 URL 未检测到 token(={page.url});仍尝试保存 cookies。"
                  "若后续 BrowserChannel 报『未登录』,请重跑本脚本确保已进入后台首页。")

        await ctx.storage_state(path=str(out_path))
        print(f"\n登录态已保存: {out_path}")
        # 仅在真正进入后台(token 出现)时回写有效期,避免半有效登录态使 expires_at 虚高
        if logged_in:
            try:
                await persist_login(app_id)
            except Exception as e:  # noqa: BLE001 —— 回写失败不影响文件已落盘;下一 tick 探测补正
                print(f"提示:登录态文件已存,但回写 DB 有效期失败({e});可稍后重跑或手动处理。")
        else:
            print("提示:未检测到 token,未回写有效期(status 维持原值)。请确认已进入后台首页后重跑。")
        # 若用户还没按 Enter(自动检测先命中),给个收尾提示,别卡住 executor
        if not enter_task.done():
            print("(可关闭浏览器窗口结束;或按 Enter)")
        await browser.close()


def main() -> None:
    if len(sys.argv) < 2:
        print("用法: python scripts/wx_login.py <app_id>")
        sys.exit(1)
    asyncio.run(capture(sys.argv[1]))


if __name__ == "__main__":
    main()
