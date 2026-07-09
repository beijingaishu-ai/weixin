// 统一后端响应包装
export interface ApiResult<T = unknown> {
  code: number
  message: string
  data: T
}

// 分页列表
export interface PageResult<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

// 可见公众号 (来自 /auth/me)
export interface VisibleMp {
  id: number
  mp_name: string
  perm_level: number | null
}

// 登录返回的用户信息
export interface LoginUser {
  id: number
  real_name: string
  role: string
  perms: string[]
}

export interface LoginResult {
  access_token: string
  refresh_token: string
  user: LoginUser
}

// /auth/me 返回
export interface MeInfo {
  id: number
  username: string
  real_name: string
  role: string
  roles: string[]
  perms: string[]
  visible_mp: VisibleMp[]
}

// 用户(后端返回 status:1启用/0禁用、roles:string[])
export interface UserItem {
  id: number
  username: string
  real_name: string
  phone?: string
  role?: string
  roles?: string[]
  status?: number
  is_active?: boolean
  last_login_at?: string
  created_at?: string
  [key: string]: unknown
}

// 角色(后端 /roles 返回 role_code / role_name / perms)
export interface RoleItem {
  role_code: string
  role_name: string
  perms?: string[]
}

// 公众号台账
export interface MpAccount {
  id: number
  mp_name: string
  app_id?: string
  app_secret?: string
  account_type?: number
  ip_whitelist_ok?: boolean
  verify_status?: string
  // 浏览器发布登录态授权(仅真实号 account_type∈{1,2};详见 docs/浏览器发布登录态授权设计.md)
  wx_login_status?: string
  wx_login_expires_at?: string | null
  remark?: string
  created_at?: string
  [key: string]: unknown
}

export interface LoginAuthStatus {
  mp_id: number
  mp_name: string
  is_mock: boolean
  wx_login_status: string
  wx_login_captured_at?: string | null
  wx_login_expires_at?: string | null
  wx_login_ttl_hours: number
  reauth_cmd?: string | null
}

// 公众号运营分配(perm_level:1只读/2编辑/3提审/4发布)
export interface Assignee {
  user_id: number
  real_name?: string
  username?: string
  perm_level: number
  assigned_at?: string
}

// 用户可访问的公众号 (GET /users/{id}/mp-accounts)
export interface UserMpAccount {
  mp_id: number
  mp_name: string
  perm_level: string
  [key: string]: unknown
}

// 审计记录
export interface AuditRecord {
  id: number
  user_id?: number
  operator?: string
  action?: string
  target?: string
  detail?: string
  ip?: string
  created_at?: string
  [key: string]: unknown
}

// ==================== M2 内容中心 ====================

// 素材 (图片/封面等)
export interface Material {
  id: number
  file_name?: string
  url: string
  type?: string
  size?: number
  width?: number
  height?: number
  mp_account_id?: number
  created_at?: string
  [key: string]: unknown
}

// 样式模板(后端 content_style_template)
export interface StyleTemplate {
  id: number
  template_name: string
  description?: string
  category: string
  header_html?: string | null
  footer_html?: string | null
  style_json?: string | null
  is_builtin?: number
  enabled?: number
  [key: string]: unknown
}

// 图文状态(content_article 段,统一状态机)
export type ArticleStatus =
  | 'TRANSFORMED'
  | 'PENDING_REVIEW'
  | 'APPROVED'
  | 'REJECTED'
  | 'DRAFT_CREATED'
  | string

// 图文(列表项不含正文;详情含 content_html)
export interface Article {
  id: number
  mp_account_id?: number
  title: string
  author?: string
  digest?: string
  content_html?: string
  cover_material_id?: number
  status: ArticleStatus
  style_template_id?: number
  content_source_url?: string
  need_open_comment?: number
  only_fans_can_comment?: number
  thumb_media_id?: string
  draft_media_id?: string
  draft_group_id?: number
  group_position?: number
  created_by?: number
  created_at?: string
  updated_at?: string
  [key: string]: unknown
}

// 图文历史版本(后端 content_article_version)
export interface ArticleVersion {
  id: number
  content_article_id: number
  version_no: number
  title?: string
  digest?: string
  change_note?: string
  created_by?: number
  created_at?: string
  [key: string]: unknown
}

// 多图文草稿组成员(后端 GroupMemberItem)
export interface DraftGroupMember {
  id: number
  title: string
  status: ArticleStatus
  group_position: number
  cover_material_id?: number
}

// 多图文草稿组(后端 content_draft_group)
export interface DraftGroup {
  id: number
  group_name?: string
  mp_account_id?: number
  status?: string
  all_approved?: boolean
  members?: DraftGroupMember[]
  created_at?: string
  [key: string]: unknown
}

// 发布任务状态(publish_task 段,统一状态机)
export type PublishStatus = 'SCHEDULED' | 'PUBLISHING' | 'PUBLISHED' | 'FAILED' | string

// 发布任务(后端 publish_task)
export interface PublishTask {
  id: number
  biz_key?: string
  content_article_id?: number
  draft_group_id?: number
  mp_account_id?: number
  publish_type?: number
  status: PublishStatus
  scheduled_at?: string
  publish_id?: string
  published_article_id?: string
  published_url?: string
  retry_count?: number
  max_retry?: number
  next_retry_at?: string
  last_errcode?: number
  last_errmsg?: string
  created_at?: string
  updated_at?: string
  [key: string]: unknown
}

// 发布流水日志(后端 publish_log,只追加)
export interface PublishLog {
  id: number
  publish_task_id: number
  phase?: string
  from_status?: string
  to_status?: string
  wx_api?: string
  request_digest?: string
  errcode?: number
  errmsg?: string
  cost_ms?: number
  created_at?: string
  [key: string]: unknown
}

// 发布统计(后端 PublishStats)
export interface PublishStats {
  total?: number
  scheduled?: number
  publishing?: number
  published?: number
  failed?: number
  success_rate?: number
  [key: string]: unknown
}

// ==================== M3 采集中心 / 映射规则 ====================

// 采集源适配器类型
export type AdapterType = 'mock' | 'rss' | 'manual' | string
// 采集源状态
export type CollectSourceStatus = 'ACTIVE' | 'PAUSED' | 'CIRCUIT_OPEN' | string

// 采集源(collect_source)
export interface CollectSource {
  id: number
  source_name: string
  adapter_type: AdapterType
  config_json?: string | null
  interval_minutes?: number
  jitter_seconds?: number
  status: CollectSourceStatus
  whitelist_confirmed?: boolean
  auth_proof_url?: string | null
  fail_count?: number
  last_run_at?: string | null
  created_at?: string
  updated_at?: string
  [key: string]: unknown
}

// 采集文章状态
export type CollectArticleStatus =
  | 'COLLECTED'
  | 'MAPPED'
  | 'TRANSFORMED'
  | 'UNMATCHED'
  | string

// 采集文章(collect_article)
export interface CollectArticle {
  id: number
  title: string
  author?: string
  url?: string
  status: CollectArticleStatus
  source_id?: number
  source_name?: string
  collected_at?: string
  unmatched_reason?: string | null
  dedup_of?: number | null
  raw_content?: string | null
  clean_content?: string | null
  summary?: string | null
  created_at?: string
  [key: string]: unknown
}

// 采集文章去重信息(GET /collect/articles/{id}/dedup-info)
export interface DedupInfo {
  is_duplicate?: boolean
  dedup_of?: number | null
  content_hash?: string | null
  simhash?: string | null
  similarity?: number | null
  duplicates?: Array<{ id: number; title?: string; similarity?: number }>
  [key: string]: unknown
}

// 采集总览统计(GET /collect/stats/overview)
export interface CollectOverview {
  sources_total?: number
  sources_active?: number
  articles_total?: number
  collected?: number
  mapped?: number
  transformed?: number
  unmatched?: number
  duplicated?: number
  [key: string]: unknown
}

// test-run / run-now 结果
export interface CollectRunResult {
  collected?: number
  duplicated?: number
  unmatched?: number
  samples?: Array<{ title?: string; author?: string; url?: string; [key: string]: unknown }>
  [key: string]: unknown
}

// 映射规则调度策略
export interface MappingSchedulePolicy {
  window_start?: string
  window_end?: string
  daily_limit?: number
  [key: string]: unknown
}

// 映射规则匹配条件
export interface MappingMatchCondition {
  include_keywords?: string[]
  exclude_keywords?: string[]
  match_scope?: string // title / content / both
  min_words?: number
  [key: string]: unknown
}

// 映射规则转换动作
export interface MappingTransformAction {
  title_template?: string
  source_statement_template?: string
  rehost_images?: boolean
  [key: string]: unknown
}

// 映射规则(mapping_rule)
export interface MappingRule {
  id: number
  rule_name: string
  target_mp_account_id?: number
  target_mp_name?: string
  source_ids?: number[]
  priority?: number
  enabled?: number
  // 后端 /rules 返回时已 json.loads 为对象
  match_condition_json?: Record<string, unknown>
  transform_action_json?: Record<string, unknown>
  schedule_policy_json?: Record<string, unknown>
  created_at?: string
  updated_at?: string
  [key: string]: unknown
}

// 映射规则试算(dry-run / preview)结果
export interface MappingDryRunResult {
  matched?: boolean
  matched_rule_id?: number
  matched_rule_name?: string
  target_mp_account_id?: number
  reason?: string
  transformed_title?: string
  transformed_content?: string
  [key: string]: unknown
}

// 待映射批处理结果(POST /mapping/run-pending)
export interface MappingRunPendingResult {
  processed?: number
  mapped?: number
  unmatched?: number
  [key: string]: unknown
}

// 映射执行记录(GET /mapping/executions)
export interface MappingExecution {
  id: number
  rule_id?: number
  rule_name?: string
  collect_article_id?: number
  collect_article_title?: string
  result?: string
  target_mp_account_id?: number
  content_article_id?: number
  message?: string
  created_at?: string
  [key: string]: unknown
}

// ==================== M4 调度 / 运营看板 ====================

// 手动触发一次全自动流水线的结果(POST /scheduler/tick)
export interface SchedulerTickResult {
  sources_due?: number
  collected?: number
  mapped_transformed?: number
  auto_submitted?: number
  auto_created_tasks?: number
  published?: number
  failed?: number
  retried?: number
  dead_letter_alerts?: number
  [key: string]: unknown
}

// 运营看板(GET /scheduler/dashboard)
export interface SchedulerDashboard {
  mp_total?: number
  sources_total?: number
  sources_circuit?: number
  collect_by_status?: Record<string, number>
  content_by_status?: Record<string, number>
  task_by_status?: Record<string, number>
  publish_success_rate?: number
  pending_review?: number
  [key: string]: unknown
}
