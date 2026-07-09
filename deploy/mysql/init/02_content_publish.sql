-- =====================================================================
-- M2 表结构:内容中心(6) + 发布引擎(2),对齐设计第 2、4、7 章。
-- 首次启动随 01_schema.sql 之后自动执行。
-- 注:content_article.collect_article_id / mapping_rule_id 指向 M3 表,
--     本阶段建为可空列、暂不加物理外键;M3 的 03_*.sql 再补外键。
-- =====================================================================
SET NAMES utf8mb4;

-- ---------- 本地素材库(与公众号无关,SHA-256 去重)----------
CREATE TABLE IF NOT EXISTS content_material (
    id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    material_type VARCHAR(16)   NOT NULL COMMENT 'image/thumb/video/voice',
    file_hash     CHAR(64)      NOT NULL COMMENT '文件内容 SHA-256, 全库去重指纹',
    file_size     INT UNSIGNED  NOT NULL DEFAULT 0,
    file_path     VARCHAR(512)  NOT NULL DEFAULT '' COMMENT '本地存储相对路径',
    origin_url    VARCHAR(1024) NOT NULL DEFAULT '' COMMENT '原始来源URL(采集图片本地化前)',
    created_by    BIGINT UNSIGNED NOT NULL,
    created_at    DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uk_hash_type (file_hash, material_type),
    KEY idx_origin (origin_url(255))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='本地素材库(与公众号无关的文件实体登记, SHA-256 去重)';

-- ---------- 素材在各公众号的微信侧引用 ----------
CREATE TABLE IF NOT EXISTS content_material_wx_ref (
    id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    material_id   BIGINT UNSIGNED NOT NULL COMMENT '本地素材(content_material)',
    mp_account_id BIGINT UNSIGNED NOT NULL COMMENT '素材被上传到的公众号',
    media_id      VARCHAR(128) NOT NULL DEFAULT '' COMMENT '永久素材 media_id; uploadimg 场景为空',
    wx_url        VARCHAR(512) NOT NULL DEFAULT '' COMMENT '微信侧URL(uploadimg/add_material 返回)',
    created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uk_mat_mp (material_id, mp_account_id) COMMENT '同号同素材只上传一次',
    KEY idx_mp_media (mp_account_id, media_id),
    CONSTRAINT fk_ref_mat FOREIGN KEY (material_id) REFERENCES content_material (id),
    CONSTRAINT fk_ref_mp  FOREIGN KEY (mp_account_id) REFERENCES mp_account (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='素材在各公众号的微信侧引用';

-- ---------- 排版样式模板 ----------
CREATE TABLE IF NOT EXISTS content_style_template (
    id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    template_name VARCHAR(64)  NOT NULL COMMENT '模板名',
    description   VARCHAR(255) NOT NULL DEFAULT '',
    category      VARCHAR(16)  NOT NULL DEFAULT 'card' COMMENT 'title/card/quote/divider/list',
    style_json    JSON NULL COMMENT '元素→内联样式映射',
    header_html   LONGTEXT NULL COMMENT '页首装饰片段',
    footer_html   LONGTEXT NULL COMMENT '页尾装饰片段(占位符 {author}/{url})',
    is_builtin    TINYINT NOT NULL DEFAULT 0 COMMENT '1=内置不可删',
    enabled       TINYINT NOT NULL DEFAULT 1,
    created_by    BIGINT UNSIGNED NOT NULL,
    is_deleted    TINYINT NOT NULL DEFAULT 0,
    created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uk_name (template_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='排版样式模板';

-- ---------- 多图文组 ----------
CREATE TABLE IF NOT EXISTS content_draft_group (
    id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    mp_account_id BIGINT UNSIGNED NOT NULL COMMENT '归属公众号(组内文章必须同号)',
    group_name    VARCHAR(64) NOT NULL DEFAULT '',
    status        VARCHAR(16) NOT NULL DEFAULT 'EDITING'
        COMMENT '组局部状态: EDITING/READY/PUBLISHED(不属于统一发文状态机)',
    created_by    BIGINT UNSIGNED NOT NULL,
    is_deleted    TINYINT NOT NULL DEFAULT 0,
    created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY idx_mp_status (mp_account_id, status),
    CONSTRAINT fk_grp_mp FOREIGN KEY (mp_account_id) REFERENCES mp_account (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='多图文组(一次 draft/add 最多8篇)';

-- ---------- 自有图文 ----------
CREATE TABLE IF NOT EXISTS content_article (
    id                    BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    mp_account_id         BIGINT UNSIGNED NOT NULL COMMENT '归属公众号',
    collect_article_id    BIGINT UNSIGNED NULL COMMENT '来源采集文章(M3); NULL=手工',
    mapping_rule_id       BIGINT UNSIGNED NULL COMMENT '生成规则(M3); NULL=手工',
    draft_group_id        BIGINT UNSIGNED NULL COMMENT '所属多图文组; NULL=单篇',
    group_position        TINYINT       NOT NULL DEFAULT 0 COMMENT '组内顺序(0起)',
    style_template_id     BIGINT UNSIGNED NULL COMMENT '套用的排版模板',
    title                 VARCHAR(64)   NOT NULL COMMENT '标题(限64字)',
    author                VARCHAR(64)   NOT NULL DEFAULT '',
    digest                VARCHAR(120)  NOT NULL DEFAULT '' COMMENT '摘要(限约120字)',
    content_html          LONGTEXT      NOT NULL COMMENT '编排后正文',
    thumb_media_id        VARCHAR(128)  NOT NULL DEFAULT '' COMMENT '封面永久素材 media_id',
    cover_material_id     BIGINT UNSIGNED NULL COMMENT '封面本地素材(content_material)',
    draft_media_id        VARCHAR(128)  NOT NULL DEFAULT '' COMMENT '草稿 media_id, draft/add 后回填',
    suggested_publish_at  DATETIME      NULL COMMENT '建议排期(映射引擎暂存; 手工稿为NULL)',
    need_open_comment     TINYINT       NOT NULL DEFAULT 0,
    only_fans_can_comment TINYINT       NOT NULL DEFAULT 0,
    content_source_url    VARCHAR(512)  NOT NULL DEFAULT '' COMMENT '原文链接',
    is_original_marked    TINYINT       NOT NULL DEFAULT 0 COMMENT '是否带原创标(采集场景)',
    status                VARCHAR(32)   NOT NULL DEFAULT 'TRANSFORMED'
        COMMENT 'TRANSFORMED/PENDING_REVIEW/APPROVED/REJECTED/DRAFT_CREATED',
    created_by            BIGINT UNSIGNED NOT NULL COMMENT '创建人; 规则自动生成时为系统账号 id=1',
    is_deleted            TINYINT       NOT NULL DEFAULT 0,
    created_at            DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at            DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uk_collect_mp (collect_article_id, mp_account_id)
        COMMENT '同采集文同号只生成一篇(NULL 不参与约束, 手工文不受限)',
    KEY idx_mp_status (mp_account_id, status),
    KEY idx_group (draft_group_id, group_position),
    CONSTRAINT fk_art_mp  FOREIGN KEY (mp_account_id) REFERENCES mp_account (id),
    CONSTRAINT fk_art_grp FOREIGN KEY (draft_group_id) REFERENCES content_draft_group (id),
    CONSTRAINT fk_art_tpl FOREIGN KEY (style_template_id) REFERENCES content_style_template (id)
    -- fk_art_col / fk_art_rule 指向 M3 表,待 03_*.sql 补
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='自有图文(绑定具体公众号的可发布内容)';

-- ---------- 图文版本快照(只追加)----------
CREATE TABLE IF NOT EXISTS content_article_version (
    id                 BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    content_article_id BIGINT UNSIGNED NOT NULL,
    version_no         INT UNSIGNED NOT NULL COMMENT '从1递增',
    title              VARCHAR(64)  NOT NULL,
    digest             VARCHAR(120) NOT NULL DEFAULT '',
    content_html       LONGTEXT     NOT NULL COMMENT '该版本正文快照',
    change_note        VARCHAR(255) NOT NULL DEFAULT '',
    created_by         BIGINT UNSIGNED NOT NULL,
    created_at         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uk_art_ver (content_article_id, version_no),
    CONSTRAINT fk_ver_art FOREIGN KEY (content_article_id) REFERENCES content_article (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='图文版本快照(每次保存/提审生成一版, 只追加)';

-- ---------- 发布任务 ----------
CREATE TABLE IF NOT EXISTS publish_task (
    id                   BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    biz_key              VARCHAR(64) NOT NULL COMMENT '幂等键: article:{id}/group:{id}',
    content_article_id   BIGINT UNSIGNED NULL COMMENT '单篇任务; 与 draft_group_id 二选一',
    draft_group_id       BIGINT UNSIGNED NULL COMMENT '多图文组任务',
    mp_account_id        BIGINT UNSIGNED NOT NULL COMMENT '冗余归属号(服务层校验一致)',
    publish_type         TINYINT  NOT NULL DEFAULT 1 COMMENT '1=freepublish 2=mass(群发,仅认证号)',
    scheduled_at         DATETIME NOT NULL COMMENT '计划发布时间',
    dispatched           TINYINT  NOT NULL DEFAULT 0 COMMENT '是否已投递(防重复投递)',
    status               VARCHAR(32) NOT NULL DEFAULT 'SCHEDULED'
        COMMENT 'SCHEDULED/PUBLISHING/PUBLISHED/FAILED; 重试 FAILED→SCHEDULED',
    publish_id           VARCHAR(64)  NOT NULL DEFAULT '' COMMENT 'freepublish/submit 回执',
    published_article_id VARCHAR(64)  NOT NULL DEFAULT '',
    published_url        VARCHAR(512) NOT NULL DEFAULT '',
    retry_count          TINYINT  NOT NULL DEFAULT 0,
    max_retry            TINYINT  NOT NULL DEFAULT 5,
    next_retry_at        DATETIME NULL COMMENT '指数退避: 60s起2倍递增封顶3600s',
    last_errcode         INT      NULL,
    last_errmsg          VARCHAR(512) NOT NULL DEFAULT '',
    created_by           BIGINT UNSIGNED NOT NULL,
    is_deleted           TINYINT  NOT NULL DEFAULT 0,
    created_at           DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at           DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uk_biz_key (biz_key),
    KEY idx_scan (status, dispatched, scheduled_at),
    KEY idx_mp_sched (mp_account_id, publish_type, scheduled_at),
    KEY idx_article (content_article_id),
    KEY idx_group (draft_group_id),
    CONSTRAINT chk_task_target CHECK ((content_article_id IS NULL) <> (draft_group_id IS NULL)),
    CONSTRAINT fk_task_art FOREIGN KEY (content_article_id) REFERENCES content_article (id),
    CONSTRAINT fk_task_grp FOREIGN KEY (draft_group_id) REFERENCES content_draft_group (id),
    CONSTRAINT fk_task_mp  FOREIGN KEY (mp_account_id) REFERENCES mp_account (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='发布任务(单篇或多图文组二选一)';

-- ---------- 发布流水日志(只追加)----------
CREATE TABLE IF NOT EXISTS publish_log (
    id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    publish_task_id BIGINT UNSIGNED NOT NULL,
    phase           VARCHAR(32)  NOT NULL COMMENT 'MATERIAL/DRAFT_ADD/FREEPUBLISH_SUBMIT/FREEPUBLISH_POLL/RESULT/RETRY/ALERT',
    from_status     VARCHAR(32)  NOT NULL DEFAULT '',
    to_status       VARCHAR(32)  NOT NULL DEFAULT '',
    wx_api          VARCHAR(128) NOT NULL DEFAULT '',
    request_digest  VARCHAR(1024) NOT NULL DEFAULT '' COMMENT '脱敏: 绝不记 token/secret',
    errcode         INT          NULL COMMENT '0=成功',
    errmsg          VARCHAR(512) NOT NULL DEFAULT '',
    cost_ms         INT UNSIGNED NOT NULL DEFAULT 0,
    created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY idx_task_time (publish_task_id, created_at),
    CONSTRAINT fk_log_task FOREIGN KEY (publish_task_id) REFERENCES publish_task (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='发布流水日志(只追加不更新)';
