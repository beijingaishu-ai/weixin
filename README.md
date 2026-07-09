# 微信公众号矩阵管理系统

> 教学课题 · M1 交付(基础框架 + RBAC + 公众号管理)
> 技术栈:Python 3.11 / FastAPI · Vue 3 / Vite / Element Plus · MySQL 8.0 / Redis 7 · Docker Compose + Nginx

面向 MCN 机构 / 新媒体运营团队"多号统一管理"的典型场景:一个团队同时运营数十个微信公众号,需要多号统一托管、员工分权操作、内容一处编排、外部内容合规采集、采集内容自动流转到自有号、最终全自动发布。完整系统设计见 [`docs/公众号管理系统设计.md`](docs/公众号管理系统设计.md)。

本仓库是该课题的 **M1 里程碑** 交付,只覆盖"地基 + 权限 + 公众号管理"三块,后续 M2–M4 的内容中心、采集、映射、自动发文按同一架构分阶段追加。

---

## 一、M1 范围

M1 对应设计文档 8.3 里程碑规划的第 1–4 周,交付如下(其余模块见文末"与后续里程碑的衔接"):

- **基础框架**:可一键 `docker compose up` 的开发/演示环境(MySQL / Redis / Nginx / FastAPI),统一响应体、统一异常处理、健康检查、启动引导(预置角色 + 超管)。
- **auth-rbac 账号权限中心**:登录、JWT 双令牌、五角色 RBAC、运营-公众号分配、`operator` 数据权限(行级)隔离。
- **mp-manager 公众号管理**:公众号档案 CRUD,AppSecret 以 AES-256-GCM 加密落库、任何接口不回显明文。
- **数据表**:M1 只建 6 张表——`sys_user` / `sys_role` / `sys_user_role` / `mp_account` / `mp_account_assign` / `audit_record`,DDL 见 [`deploy/mysql/init/01_schema.sql`](deploy/mysql/init/01_schema.sql)(唯一事实源,对齐设计第 2 章)。

> 说明:`wx-gateway`、`content-center`、`collector`、`mapping-engine`、`publish-engine`、`scheduler` 及 Celery `worker` / `beat` 属 M2 及以后阶段,当前 `docker-compose.yml` 中相关服务以注释形式预留。

---

## 二、技术栈

| 层次 | 选型 |
|------|------|
| 后端框架 | FastAPI 0.115 + Uvicorn(Python 3.11,原生 async,`/docs` 自动 OpenAPI) |
| ORM / 迁移 | SQLAlchemy 2.0(async + aiomysql);生产迁移用 Alembic,教学期用 `deploy/mysql/init` 建表 |
| 配置 / 校验 | Pydantic 2 + pydantic-settings |
| 安全 | bcrypt(密码哈希,cost=12)、PyJWT(HS256 双令牌)、cryptography(AppSecret AES-256-GCM) |
| 缓存 / 队列 | Redis 7(会话/令牌缓存;M2 起兼任 Celery broker) |
| 前端 | Vue 3 + TypeScript + Vite 5 + Element Plus + Pinia + Vue Router + axios |
| 编排 / 接入 | Docker Compose + Nginx 1.25(静态资源直出 + `/api` 反向代理) |
| 测试 | pytest + pytest-asyncio + aiosqlite(sqlite 内存库跑集成用例) |

---

## 三、目录结构

```
weixin/
├── docker-compose.yml           # 编排:mysql / redis / api / nginx(worker、beat 为 M2+ 注释预留)
├── .env.example                 # 根级环境样例(compose 变量插值 + api 容器 env_file)
├── docs/
│   └── 公众号管理系统设计.md     # 完整系统设计(18 表 / 状态机 / 合规红线 / 里程碑)
├── deploy/
│   ├── mysql/init/01_schema.sql # M1 建表 DDL(6 张表,MySQL 首启自动执行)
│   └── nginx/nginx.conf         # 前端静态直出 + /api 反代 + /internal 屏蔽为 404
├── backend/                     # FastAPI 后端(api / worker / beat 共用镜像)
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── .env.example             # 后端本地开发环境样例
│   └── app/
│       ├── main.py              # 应用工厂:挂载路由、注册异常、启动跑 seeds
│       ├── seeds.py             # 启动引导:预置五角色 + 首个超级管理员(幂等)
│       ├── core/                # 地基
│       │   ├── config.py        #   全局配置(env 单例)
│       │   ├── db.py            #   异步引擎 / Session
│       │   ├── redis.py         #   Redis 连接
│       │   ├── security.py      #   bcrypt 密码 + JWT 双令牌编解码
│       │   ├── crypto.py        #   AppSecret AES-256-GCM 加解密(全系统唯一入口)
│       │   ├── response.py      #   统一响应体
│       │   ├── exceptions.py    #   统一异常处理
│       │   └── audit.py         #   审计记录写入
│       ├── models/              # ORM 模型(user / mp_account / audit)
│       └── modules/
│           ├── auth_rbac/       # 账号权限中心(permissions.py 固化角色→权限点、deps.py 数据权限)
│           └── mp_manager/      # 公众号管理
└── frontend/                    # Vue 3 + Vite 管理后台
    ├── package.json
    └── vite.config.ts
```

---

## 四、快速开始

### 方式 A:Docker 一键启动(推荐用于演示)

在仓库根目录执行:

```bash
# 1) 复制环境样例
cp .env.example .env

# 2) 生成两把密钥并填入 .env
#    AppSecret 加密主密钥(AES-256,32 字节 base64)
python -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"
#    JWT 签名密钥(长随机串)
python -c "import secrets;print(secrets.token_urlsafe(48))"
```

把上面两条命令的输出分别写入 `.env` 的 `MP_SECRET_MASTER_KEY=` 与 `JWT_SECRET_KEY=`,并把 `MYSQL_PASSWORD` / `MYSQL_ROOT_PASSWORD` / `INTERNAL_TOKEN` 改成自己的值。然后:

```bash
# 3) 构建并后台启动全栈
docker compose up -d --build
```

启动后访问:

| 地址 | 说明 |
|------|------|
| <http://localhost/> | 前端管理后台(Nginx 静态直出) |
| <http://localhost/api/v1/> | 后端接口(Nginx 反代到 api:8000) |
| <http://localhost/docs> | Swagger 交互文档 |
| <http://localhost/health> | 健康检查 |

**默认超级管理员**:`admin` / `Admin@12345`(由 `.env` 的 `SUPER_ADMIN_USERNAME` / `SUPER_ADMIN_PASSWORD` 决定,仅当该账号不存在时创建)。
⚠️ **首次登录后请立即修改密码**,并在生产环境改掉 `.env` 里的默认口令与全部密钥。

> 前端静态资源由 Nginx 挂载 `frontend/dist/` 提供;若该目录尚未构建,请先在 `frontend/` 执行 `npm install && npm run build`,或按"方式 B"以 Vite 开发服务器运行前端。

### 方式 B:本地开发

**后端**(在 `backend/` 目录):

```bash
python -m venv .venv
# Windows PowerShell:  .venv\Scripts\Activate.ps1
# Linux / macOS:       source .venv/bin/activate
pip install -r requirements.txt

# 配置本地环境:复制并按需修改(至少填 MP_SECRET_MASTER_KEY / JWT_SECRET_KEY,
# 并把 MYSQL_HOST / REDIS_HOST 指向本地或容器)
cp .env.example .env

# 启动(热重载),默认 http://127.0.0.1:8000,文档在 /docs
uvicorn app.main:app --reload
```

> 本地开发需自备可连的 MySQL 8.0 与 Redis 7(可只 `docker compose up -d mysql redis` 起这两个依赖)。MySQL 首启会自动执行 `deploy/mysql/init/01_schema.sql` 建表。

### 方式 C:本地零依赖模式(无 Docker / 无 MySQL / 无 Redis,最省事)

只装了 Python 的机器直接跑起来演示,数据库用 SQLite 文件、Redis 用内存替身。**仅供本地开发/课堂演示,不可用于生产或验收**。

```bash
cd backend
python -m venv .venv
# Windows PowerShell:  .venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt        # 比 requirements.txt 多一个 fakeredis
python run_local.py                        # 默认 http://127.0.0.1:8000,文档 /docs
```

- 自动建表并预置角色与超管,登录 `admin / Admin@12345`。
- 数据存 `backend/dev_local.db`,删掉该文件即可重置。
- 前端照常 `cd frontend && npm run dev`(Vite 代理到 :8000)。

**前端**(在 `frontend/` 目录):

```bash
npm install
npm run dev        # Vite 开发服务器,默认 http://localhost:5173
```

开发态前端通过 Vite 代理(见 `vite.config.ts`)访问后端 `/api`。

---

## 五、运行测试

```bash
cd backend
pytest
```

测试使用 `aiosqlite` 内存库,无需外部 MySQL/Redis 即可跑核心用例(数据权限隔离、越权拦截等)。设计中约定的最小验收链条见 8.3:建 admin → 录测试号凭据 → verify 通过 → 建 operator → 分配 → 用 operator 登录验证"列表隔离 + 403 越权拦截"。

---

## 六、五角色与权限矩阵(简表)

功能权限由角色决定(固化在 `backend/app/modules/auth_rbac/permissions.py`);数据可见范围(能看到哪些公众号)另由 `mp_account_assign` 决定。

| 角色 (`role_code`) | 定位 | 数据范围 | 功能权限概览 |
|---|---|---|---|
| `super_admin` 超级管理员 | 系统最高权限 | 全部号 | 全部权限(含 `system:config:manage`、号级审核开关) |
| `admin` 管理员 | 日常运营管理 | 全部号 | 除系统配置外的全部权限;用户管理与公众号分配 |
| `chief_editor` 主编 | 内容与采集负责人 | 全部号 | 内容/采集/映射/发布/审核全流程;不管账号 |
| `operator` 运营 | 一线运营 | **仅被分配的号** | 查看/编辑/提审自己名下号的内容与素材,查看发布任务 |
| `auditor` 审核员 | 内容合规把关 | 全部号 | 内容审核(通过/驳回)、查看发布日志 |

> `super_admin` / `admin` / `chief_editor` / `auditor` 为"全号可见"角色特权,不走 `mp_account_assign`;只有 `operator` 的可见集合严格来自分配表。`operator` 号内还有分级权限(`perm_level`:1 只读 / 2 编辑 / 3 编辑+提审 / 4 可触发发布,逐级包含)。

---

## 七、关键安全约定

- **AppSecret 加密不回显**:`mp_account.app_secret_cipher` 以 AES-256-GCM 加密落库(布局 `nonce(12B) || ciphertext || tag(16B)`),主密钥仅存环境变量 `MP_SECRET_MASTER_KEY`,AAD 绑定 `app_id + key_version` 防跨行/跨版本挪用,支持密钥轮换。加解密收敛在 `app/core/crypto.py` 唯一入口;任何接口只返回脱敏值(`mask_secret`,仅末 4 位),永不回显明文。
- **密码单向哈希**:登录密码用 bcrypt(cost=12)单向哈希,绝不可逆存储。
- **JWT 双令牌**:HS256 签发,访问令牌 30 分钟、刷新令牌 7 天,载荷含 `sub/role/jti/typ/exp`;令牌黑/白名单由 auth-rbac 借 Redis 维护,用户被禁用即时失效。
- **operator 数据权限隔离**:`operator` 的可见公众号集合唯一来自 `mp_account_assign`,由 `deps.get_visible_mp_ids` 统一注入并对详情/写操作叠加 `perm_level` 校验,防止水平越权(IDOR)。
- **access_token 零落库**:微信 `access_token` 一律只进 Redis(TTL = `expires_in - 300`,约 6900s),数据库中不出现任何可直接调用微信 API 的活凭据(M2 wx-gateway 生效)。
- **`/internal` 不对外**:`/api/v1/internal/*` 是 wx-gateway 内部凭据接口,Nginx 直接返回 404、仅容器内网可达(见 `deploy/nginx/nginx.conf`);内部调用另持共享令牌 `INTERNAL_TOKEN`。
- **网络隔离与出口白名单**:MySQL/Redis/api 不暴露宿主端口,外部流量只经 Nginx 进入;调用微信 API 的出口公网 IP 须逐一加入各公众号后台 IP 白名单(M2 起,否则报 `40164`)。

---

## 八、M1 验收点对照(设计 8.3）

| 验收点 | 落地位置 |
|---|---|
| 可一键 `docker compose up` 的开发环境 | `docker-compose.yml` + `backend/Dockerfile` + `deploy/` |
| 六张 M1 表建表迁移 | `deploy/mysql/init/01_schema.sql`(MySQL 首启自动执行) |
| 登录 / JWT / 角色权限接口 | `app/core/security.py`、`app/modules/auth_rbac/`、`app/seeds.py` |
| 公众号 CRUD(AppSecret 加密) | `app/modules/mp_manager/`、`app/core/crypto.py`、`app/models/mp_account.py` |
| 管理员建运营账号并分配公众号 | `mp_account_assign` + auth-rbac 分配接口 |
| 运营登录后仅能看到自己名下的号 | `deps.get_visible_mp_ids` + `mp_account_assign`（数据权限隔离） |
| AppSecret 任何接口不回显明文 | `crypto.mask_secret`（仅末 4 位) |
| 接口权限核验清单 | 以官方《接口权限说明》页 + 真机验证逐项确认(测试号/未认证订阅号的草稿箱、发布接口按"不可用"保守假设) |

---

## 九、与后续里程碑的衔接（M2–M4)

M1 的架构与边界为后续阶段预留了扩展点,后续里程碑不改动核心架构、只按阶段追加模块与数据表:

| 里程碑 | 范围 | 主要新增 |
|---|---|---|
| **M2** 内容中心 + wx-gateway + 手动发文 | content-center、wx-gateway(含 Mock/Real 通道)、wangEditor 编辑器 | `content_article`/`content_material`;access_token 中控(Redis 缓存 + 并发锁);建草稿→提交发布→轮询手动链路;启用 Celery `worker`/`beat`。**硬性前置**:教师/课程组提供至少一个已认证公众号做真实链路终验,Mock 通道为主线验收 |
| **M3** 采集中心 + 映射引擎 | collector(mock/rss/manual 三通道)、mapping-engine | `collect_source`/`collect_article`(url_hash + simhash 去重);`mapping_rule` 多源→目标号;原创转载拦截 |
| **M4** 全自动流水线 + 审核 + 告警统计 | publish-engine 自动化、scheduler、审核工作流、看板 | 审核队列、定时策略、失败重试(指数退避)、告警、统计看板、一键下架 |

已在 M1 预留的衔接点:`docker-compose.yml` 注释中的 `worker`/`beat` 服务(与 api 同镜像)、`account_type=3`(测试/模拟号,M2 走 MockChannel)、`need_review` 与 `PUBLISH_REVIEW_ENABLED` 双层审核开关、`audit_record` 审计表。

---

## 十、合规提示(采集与转载红线)

本系统的采集与发文严守合规红线,实现必须遵守(完整口径见设计第 8 章及第 5、7 章):

- **只对接"有权获取"的数据来源**:内容方自有公开 RSS/API、人工授权后的运营手工导入、教学 Mock 数据;**不实现任何反爬对抗逻辑**,不破解或绕过任何访问控制,遵守 robots 协议与合理抓取频率。
- **采集只进候选池,发布必须过人工审核**:采集所得不自动发布;默认开启人工审核卡点(`PENDING_REVIEW`),两层审核开关同时关闭才允许自动过审,且每次自动过审均写 `audit_record` 留痕。
- **原创转载须先取得授权**:带"原创"标的文章转载须由运营线下取得源公众号授权,并在 `collect_source` 人工登记(`whitelist_confirmed=1`,留存 `auth_proof_url`);微信无任何 API 可查询他人转载白名单,系统一律以人工登记为准。未登记授权的原创文章由映射引擎直接拦截(置 `UNMATCHED`)。
- **凭据只纳管自有/获授权公众号**:禁止收集、买卖、外传他人公众号凭据;凭据仅用于本系统功能。凭据出借、代刷等违反《微信公众平台服务协议》的行为,系统在设计上不提供任何多主体凭据共享功能。
- **发布仅上主页、不推送粉丝**:自动发布只发到公众号主页;推送粉丝须走群发接口且受频次配额约束(认证订阅号 1 次/天、服务号 4 次/月),由 publish-engine 做配额校验(M4)。
