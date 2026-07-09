-- =====================================================================
-- M3 表结构:采集中心(2) + 映射引擎(2),对齐设计第 2、5、6 章。
-- 至此全库 18 张表齐备。
-- 说明:simhash 存 16 位十六进制字符串;simhash_b0..b3 为 4 段各 16 位普通索引列,
--       由采集服务写入前计算填充(未用 MySQL 生成列,以便 ORM 在 SQLite 测试库通用)。
-- =====================================================================
SET NAMES utf8mb4;

-- ---------- 采集源配置 ----------
CREATE TABLE IF NOT EXISTS collect_source (
    id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    source_name         VARCHAR(64)  NOT NULL COMMENT '采集源名称',
    adapter_type        VARCHAR(32)  NOT NULL COMMENT 'mock/rss/manual(其他仅保留扩展点,不实现)',
    config_json         JSON NULL COMMENT '适配器私有配置,如 rss:{"feed_url":"..."}',
    cursor_json         JSON NULL COMMENT '增量采集游标,适配器自管理',
    interval_minutes    INT UNSIGNED NOT NULL DEFAULT 120 COMMENT '采集间隔(分钟)',
    jitter_seconds      INT UNSIGNED NOT NULL DEFAULT 60 COMMENT '随机抖动上限(秒)',
    next_run_at         DATETIME NULL COMMENT '下次应执行时间',
    whitelist_confirmed TINYINT NOT NULL DEFAULT 0
        COMMENT '原创转载授权已人工确认(微信无API可查他人白名单;线下取得授权后手工置位;publish_status=2 时自动回写0)',
    auth_proof_url      VARCHAR(512) NOT NULL DEFAULT '' COMMENT '授权凭证链接',
    status              VARCHAR(16) NOT NULL DEFAULT 'ACTIVE'
        COMMENT '源局部状态: ACTIVE/PAUSED/CIRCUIT_OPEN(不属统一发文状态机)',
    fail_count          INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '连续失败次数, >=5 置 CIRCUIT_OPEN',
    created_by          BIGINT UNSIGNED NOT NULL,
    is_deleted          TINYINT NOT NULL DEFAULT 0,
    created_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY idx_scan (status, next_run_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='采集源配置(适配器模型,见第5章)';

-- ---------- 采集文章库 ----------
CREATE TABLE IF NOT EXISTS collect_article (
    id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    source_id           BIGINT UNSIGNED NOT NULL,
    title               VARCHAR(255)  NOT NULL,
    author              VARCHAR(64)   NOT NULL DEFAULT '' COMMENT '原文作者(版权溯源)',
    url                 VARCHAR(1024) NOT NULL DEFAULT '' COMMENT '原文链接',
    url_hash            CHAR(64)      NOT NULL COMMENT 'SHA-256(规范化URL), 精确去重',
    simhash             CHAR(16)      NOT NULL DEFAULT '0' COMMENT '正文64位SimHash(十六进制)',
    simhash_b0          INT UNSIGNED  NOT NULL DEFAULT 0 COMMENT '高16位段',
    simhash_b1          INT UNSIGNED  NOT NULL DEFAULT 0,
    simhash_b2          INT UNSIGNED  NOT NULL DEFAULT 0,
    simhash_b3          INT UNSIGNED  NOT NULL DEFAULT 0 COMMENT '低16位段',
    dedup_of            BIGINT UNSIGNED NULL COMMENT '近似去重命中指向的留存文章;本行置 UNMATCHED',
    digest              VARCHAR(255)  NOT NULL DEFAULT '',
    raw_html            LONGTEXT      NOT NULL COMMENT '原始HTML留档',
    clean_html          LONGTEXT      NOT NULL COMMENT '清洗后正文(映射转换与指纹输入)',
    cover_url           VARCHAR(512)  NOT NULL DEFAULT '',
    is_original_marked  TINYINT       NOT NULL DEFAULT 0 COMMENT '源文是否带原创标',
    unmatched_reason    VARCHAR(255)  NOT NULL DEFAULT '' COMMENT '无命中/去重/原创拦截原因',
    source_publish_time DATETIME      NULL,
    status              VARCHAR(32)   NOT NULL DEFAULT 'COLLECTED'
        COMMENT 'COLLECTED/UNMATCHED/MAPPED/TRANSFORMED',
    collected_at        DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    is_deleted          TINYINT       NOT NULL DEFAULT 0,
    created_at          DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uk_url_hash (url_hash),
    KEY idx_source_status (source_id, status),
    KEY idx_dedup (dedup_of),
    KEY idx_sb0 (simhash_b0), KEY idx_sb1 (simhash_b1),
    KEY idx_sb2 (simhash_b2), KEY idx_sb3 (simhash_b3),
    CONSTRAINT fk_ca_source FOREIGN KEY (source_id) REFERENCES collect_source (id),
    CONSTRAINT fk_ca_dedup  FOREIGN KEY (dedup_of) REFERENCES collect_article (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='采集文章库(全网内容池,未绑定自有公众号)';

-- ---------- 映射规则 ----------
CREATE TABLE IF NOT EXISTS mapping_rule (
    id                    BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    rule_name             VARCHAR(64) NOT NULL,
    target_mp_account_id  BIGINT UNSIGNED NOT NULL COMMENT '映射目标(一条规则一个目标号)',
    match_condition_json  JSON NULL COMMENT '筛选条件',
    transform_action_json JSON NULL COMMENT '转换动作(图片仅标记待转存)',
    schedule_policy_json  JSON NULL COMMENT '排期策略(算 suggested_publish_at,不建任务)',
    priority              INT      NOT NULL DEFAULT 100 COMMENT '数值越大越优先,命中即停',
    enabled               TINYINT  NOT NULL DEFAULT 1,
    created_by            BIGINT UNSIGNED NOT NULL,
    is_deleted            TINYINT  NOT NULL DEFAULT 0,
    created_at            DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at            DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY idx_target (target_mp_account_id),
    KEY idx_enabled_priority (enabled, priority),
    CONSTRAINT fk_rule_mp FOREIGN KEY (target_mp_account_id) REFERENCES mp_account (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='映射规则(筛选+转换+排期策略)';

-- ---------- 规则-采集源关联 ----------
CREATE TABLE IF NOT EXISTS mapping_rule_source (
    id         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    rule_id    BIGINT UNSIGNED NOT NULL,
    source_id  BIGINT UNSIGNED NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uk_rule_source (rule_id, source_id),
    KEY idx_source (source_id),
    CONSTRAINT fk_mrs_rule FOREIGN KEY (rule_id) REFERENCES mapping_rule (id),
    CONSTRAINT fk_mrs_src  FOREIGN KEY (source_id) REFERENCES collect_source (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='规则-采集源关联(纯关系表,物理删除)';
