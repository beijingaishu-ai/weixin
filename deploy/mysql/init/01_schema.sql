-- =====================================================================
-- 微信公众号矩阵管理系统 —— M1 表结构(唯一 DDL 事实源,对齐设计第 2 章)
-- 由 MySQL 容器首次启动时自动执行(/docker-entrypoint-initdb.d)。
-- M1 仅建 6 张表:sys_user / sys_role / sys_user_role /
--                mp_account / mp_account_assign / audit_record
-- M2~M4 的其余 12 张表在对应阶段追加 02_*.sql、03_*.sql。
-- =====================================================================
SET NAMES utf8mb4;

-- ---------- 用户 ----------
CREATE TABLE IF NOT EXISTS sys_user (
    id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    username      VARCHAR(64)  NOT NULL COMMENT '登录名; 软删时改写为 username#id 以释放唯一键',
    password_hash CHAR(60)     NOT NULL COMMENT 'bcrypt 哈希(cost=12), 永不存明文',
    real_name     VARCHAR(64)  NOT NULL DEFAULT '' COMMENT '姓名',
    phone         VARCHAR(20)  NOT NULL DEFAULT '' COMMENT '手机号',
    email         VARCHAR(128) NOT NULL DEFAULT '' COMMENT '邮箱',
    status        TINYINT      NOT NULL DEFAULT 1 COMMENT '1=启用 0=禁用(禁用即时踢下线)',
    last_login_at DATETIME     NULL,
    is_deleted    TINYINT      NOT NULL DEFAULT 0 COMMENT '软删除: 0=正常 1=已删',
    created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uk_username (username),
    KEY idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='系统用户(角色维度固定五角色, 见 sys_role.role_code)';

-- ---------- 角色 ----------
CREATE TABLE IF NOT EXISTS sys_role (
    id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    role_code   VARCHAR(32)  NOT NULL COMMENT '固定五角色: super_admin/admin/chief_editor/operator/auditor',
    role_name   VARCHAR(64)  NOT NULL COMMENT '角色显示名',
    is_builtin  TINYINT      NOT NULL DEFAULT 0 COMMENT '1=内置角色不可删',
    remark      VARCHAR(255) NOT NULL DEFAULT '',
    created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uk_role_code (role_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='角色(功能权限维度, 数据权限见 mp_account_assign)';

-- ---------- 用户-角色 ----------
CREATE TABLE IF NOT EXISTS sys_user_role (
    id         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    user_id    BIGINT UNSIGNED NOT NULL,
    role_id    BIGINT UNSIGNED NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uk_user_role (user_id, role_id),
    KEY idx_role (role_id),
    CONSTRAINT fk_ur_user FOREIGN KEY (user_id) REFERENCES sys_user (id),
    CONSTRAINT fk_ur_role FOREIGN KEY (role_id) REFERENCES sys_role (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='用户-角色多对多(纯关系表, 物理删除)';

-- ---------- 公众号档案 ----------
CREATE TABLE IF NOT EXISTS mp_account (
    id                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    mp_name           VARCHAR(64)  NOT NULL COMMENT '公众号名称',
    wx_original_id    VARCHAR(32)  NOT NULL DEFAULT '' COMMENT '原始ID(gh_ 开头)',
    app_id            VARCHAR(32)  NOT NULL COMMENT '开发者 AppID',
    app_secret_cipher VARBINARY(512) NOT NULL
        COMMENT 'AppSecret 密文, AES-256-GCM; nonce(12B)||ciphertext||tag(16B); 主密钥 MP_SECRET_MASTER_KEY; AAD=app_id:key_version',
    auth_mode         TINYINT      NOT NULL DEFAULT 1 COMMENT '1=开发者密钥直连 2=第三方平台授权(预留)',
    key_version       SMALLINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '加密主密钥版本, 支持轮换',
    account_type      TINYINT      NOT NULL COMMENT '1=订阅号 2=服务号 3=测试或模拟号(=3 走 MockChannel)',
    is_verified       TINYINT      NOT NULL DEFAULT 0 COMMENT '是否微信认证; 群发接口仅认证号可用',
    need_review       TINYINT      NOT NULL DEFAULT 1 COMMENT '号级审核开关(默认开), 仅 super_admin 可改',
    avatar_url        VARCHAR(512) NOT NULL DEFAULT '',
    qrcode_url        VARCHAR(512) NOT NULL DEFAULT '',
    ip_whitelist_ok   TINYINT      NOT NULL DEFAULT 0 COMMENT '出口IP是否已加入该号后台白名单(40164 置0)',
    last_verified_at  DATETIME     NULL COMMENT '最近一次凭据验证成功时间',
    wx_login_captured_at DATETIME  NULL COMMENT '浏览器发布登录态:最近扫码成功、storage_state 落盘时刻(仅续扫回写)',
    wx_login_expires_at  DATETIME  NULL COMMENT '= captured_at + ttl_hours;发布前置与巡检唯一时间判据',
    wx_login_ttl_hours   SMALLINT UNSIGNED NOT NULL DEFAULT 48 COMMENT '行级登录态有效期(小时),覆盖全局 WX_LOGIN_TTL_HOURS',
    wx_login_status      VARCHAR(16) NOT NULL DEFAULT 'UNAUTHORIZED' COMMENT 'WxLoginStatus 枚举快照(UNAUTHORIZED/AUTHORIZED/EXPIRING/EXPIRED/REVOKED)',
    wx_login_alerted_at  DATETIME  NULL COMMENT '续扫告警去重戳:告警后置时间,续扫成功清空',
    status            TINYINT      NOT NULL DEFAULT 1 COMMENT '1=正常 2=凭据异常 0=停用',
    remark            VARCHAR(255) NOT NULL DEFAULT '',
    created_by        BIGINT UNSIGNED NOT NULL COMMENT '录入人(sys_user.id)',
    is_deleted        TINYINT      NOT NULL DEFAULT 0,
    created_at        DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at        DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uk_app_id (app_id),
    KEY idx_status (status),
    KEY idx_login_status (wx_login_status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='公众号档案';

-- ---------- 运营-公众号分配 ----------
CREATE TABLE IF NOT EXISTS mp_account_assign (
    id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    user_id       BIGINT UNSIGNED NOT NULL COMMENT '运营用户',
    mp_account_id BIGINT UNSIGNED NOT NULL COMMENT '被分配的公众号',
    perm_level    TINYINT NOT NULL DEFAULT 2
        COMMENT '号内权限: 1=只读 2=编辑 3=编辑+提审 4=可发布(逐级包含)',
    assigned_by   BIGINT UNSIGNED NOT NULL COMMENT '分配人(管理员)',
    deleted_flag  BIGINT UNSIGNED NOT NULL DEFAULT 0
        COMMENT '软删占位: 0=有效; 取消分配时 UPDATE 为本行 id, 使唯一键可被重新占用',
    created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uk_user_mp (user_id, mp_account_id, deleted_flag),
    KEY idx_mp (mp_account_id),
    CONSTRAINT fk_asg_user FOREIGN KEY (user_id) REFERENCES sys_user (id),
    CONSTRAINT fk_asg_mp   FOREIGN KEY (mp_account_id) REFERENCES mp_account (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='运营-公众号分配(多对多+权限属性), operator 数据权限的唯一依据';

-- ---------- 审计记录 ----------
CREATE TABLE IF NOT EXISTS audit_record (
    id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    biz_type    VARCHAR(32) NOT NULL DEFAULT 'content_article' COMMENT '业务类型(M1: sys_user/mp_account/mp_account_assign)',
    biz_id      BIGINT UNSIGNED NOT NULL COMMENT '业务主键(弱关联, 不建物理外键)',
    action      VARCHAR(16) NOT NULL COMMENT '短码: auth.login/user.create/mp.assign 等; M4 起含 SUBMIT/APPROVE/REJECT/AUTO_APPROVE',
    from_status VARCHAR(32) NOT NULL DEFAULT '',
    to_status   VARCHAR(32) NOT NULL DEFAULT '',
    auditor_id  BIGINT UNSIGNED NULL COMMENT '操作人; 0=系统自动',
    opinion     VARCHAR(512) NOT NULL DEFAULT '' COMMENT '意见/备注',
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY idx_biz (biz_type, biz_id, created_at),
    KEY idx_auditor (auditor_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='审计/审核记录(只追加, 责任追溯留痕)';
