"""全局配置:从环境变量 / .env 读取,单例注入各模块。

设计对齐:JWT 双令牌(3.7)、AppSecret 加密主密钥(3.3.2)、
全局审核开关 PUBLISH_REVIEW_ENABLED(第7章,M1 仅定义、M2+ 生效)。
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    # ---- 应用 ----
    APP_NAME: str = "微信公众号矩阵管理系统"
    APP_ENV: str = "dev"
    API_PREFIX: str = "/api/v1"
    DEBUG: bool = True

    # ---- MySQL ----
    MYSQL_HOST: str = "127.0.0.1"
    MYSQL_PORT: int = 3306
    MYSQL_USER: str = "mpuser"
    MYSQL_PASSWORD: str = "mp_pass_change_me"
    MYSQL_DB: str = "wx_mp"
    # 完整 URL 覆盖(测试用 sqlite+aiosqlite:///...);置空则由上面分片拼装
    DATABASE_URL: str | None = None

    # ---- Redis ----
    REDIS_HOST: str = "127.0.0.1"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str = ""
    REDIS_DB: int = 0

    # ---- JWT(HS256 双令牌,3.7)----
    JWT_SECRET_KEY: str = "dev-insecure-change-me"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    LOGIN_MAX_FAIL: int = 5          # 连续错误锁定阈值
    LOGIN_LOCK_MINUTES: int = 10

    # ---- AppSecret 加密(AES-256-GCM,3.3.2)----
    # 32 字节主密钥的 base64;为空时 crypto 层按当前版本报错提示配置
    MP_SECRET_MASTER_KEY: str = ""
    MP_SECRET_KEY_VERSION: int = 1

    # ---- wx-gateway 内部凭据接口共享令牌 ----
    INTERNAL_TOKEN: str = "dev-internal-token"

    # ---- 首启超级管理员引导 ----
    SUPER_ADMIN_USERNAME: str = "admin"
    SUPER_ADMIN_PASSWORD: str = "Admin@12345"

    # ---- 全局发布审核开关(M2+)----
    PUBLISH_REVIEW_ENABLED: bool = True

    # ---- 火山方舟 Coding Plan(AI 能力接入)----
    VOLC_ARK_API_KEY: str = ""
    VOLC_ARK_BASE_URL: str = "https://ark.cn-beijing.volces.com/api/coding/v3"
    VOLC_ARK_MODEL: str = "ark-code-latest"
    VOLC_ARK_TIMEOUT_SECONDS: int = 60

    # ---- 真实浏览器发布(BrowserChannel,account_type != 3 时启用)----
    # 每个公众号的登录态(storage_state)存 {WX_STORAGE_STATE_DIR}/{app_id}.json
    WX_STORAGE_STATE_DIR: str = "secrets/wx_state"
    WX_HEADLESS: bool = True            # 生产无头;首次调试可设 false 观察
    WX_PUBLISH_DRY_RUN: bool = False    # true=只建草稿保存,不点『发表/群发』(安全试跑)
    WX_DEBUG_SHOT_DIR: str = "media/wx_debug"  # 每步/失败截图目录(排障与选择器校准用)
    WX_STEP_TIMEOUT_MS: int = 20000     # 单步等待选择器超时
    WX_MASS_CONFIRM_WAIT_S: int = 180   # 群发:等待管理员扫码/短信确认的最长秒数
    # 登录态扫码授权有效期(2 天窗口,可配);详见 docs/浏览器发布登录态授权设计.md
    WX_LOGIN_TTL_HOURS: int = 48        # 扫码后有效期(小时);行级 mp_account.wx_login_ttl_hours 可覆盖
    WX_LOGIN_WARN_HOURS: int = 6        # 临期提前量:进 EXPIRING 并触发续扫告警的提前小时数

    # ---- 告警 webhook(死信告警,可选)----
    ALERT_WEBHOOK_URL: str = ""

    @property
    def sqlalchemy_database_uri(self) -> str:
        if self.DATABASE_URL:
            return self.DATABASE_URL
        return (
            f"mysql+aiomysql://{self.MYSQL_USER}:{self.MYSQL_PASSWORD}"
            f"@{self.MYSQL_HOST}:{self.MYSQL_PORT}/{self.MYSQL_DB}?charset=utf8mb4"
        )

    @property
    def redis_url(self) -> str:
        auth = f":{self.REDIS_PASSWORD}@" if self.REDIS_PASSWORD else ""
        return f"redis://{auth}{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
