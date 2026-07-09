import { httpDelete, httpGet, httpPatch, httpPost, httpPut } from './http'
import type {
  AuditRecord,
  Article,
  ArticleStatus,
  ArticleVersion,
  Assignee,
  CollectArticle,
  CollectArticleStatus,
  CollectOverview,
  CollectRunResult,
  CollectSource,
  DedupInfo,
  DraftGroup,
  LoginAuthStatus,
  LoginResult,
  MappingDryRunResult,
  MappingExecution,
  MappingRule,
  MappingRunPendingResult,
  Material,
  MeInfo,
  MpAccount,
  PageResult,
  PublishLog,
  PublishStats,
  PublishTask,
  RoleItem,
  SchedulerDashboard,
  SchedulerTickResult,
  StyleTemplate,
  UserItem,
  UserMpAccount,
} from './types'

// -------- Auth --------
export function apiLogin(username: string, password: string) {
  return httpPost<LoginResult>('/auth/login', { username, password })
}
export function apiLogout() {
  return httpPost<null>('/auth/logout')
}
export function apiMe() {
  return httpGet<MeInfo>('/auth/me')
}

// -------- Users --------
export interface UserListQuery {
  page?: number
  page_size?: number
  keyword?: string
}
export function apiListUsers(query: UserListQuery = {}) {
  return httpGet<PageResult<UserItem>>('/users', { params: query })
}
export interface CreateUserPayload {
  username: string
  real_name: string
  password: string
  role_code: string
  phone?: string
}
export function apiCreateUser(payload: CreateUserPayload) {
  return httpPost<{ id: number }>('/users', payload)
}
// 后端 UserUpdateReq: {real_name?, phone?, status?(0/1)}
export interface UpdateUserPayload {
  real_name?: string
  phone?: string
  status?: number
}
export function apiUpdateUser(id: number, payload: UpdateUserPayload) {
  return httpPut<null>(`/users/${id}`, payload)
}
// 后端要 role_codes: string[]
export function apiSetUserRoles(id: number, roleCodes: string[]) {
  return httpPut<null>(`/users/${id}/roles`, { role_codes: roleCodes })
}
// 后端要 new_password
export function apiResetPassword(id: number, password: string) {
  return httpPut<null>(`/users/${id}/password`, { new_password: password })
}
export function apiUserMpAccounts(id: number) {
  return httpGet<UserMpAccount[]>(`/users/${id}/mp-accounts`)
}

// -------- Roles --------
export function apiListRoles() {
  return httpGet<RoleItem[]>('/roles')
}

// -------- MP Accounts --------
export interface MpListQuery {
  page?: number
  page_size?: number
  keyword?: string
}
export function apiListMpAccounts(query: MpListQuery = {}) {
  return httpGet<PageResult<MpAccount>>('/mp-accounts', { params: query })
}
export function apiGetMpAccount(id: number) {
  return httpGet<MpAccount>(`/mp-accounts/${id}`)
}
export interface CreateMpPayload {
  mp_name: string
  account_type: number // 1=订阅号 2=服务号 3=测试/模拟号
  app_id: string
  app_secret: string
  wx_original_id?: string
  is_verified?: number
  remark?: string
}
export function apiCreateMpAccount(payload: CreateMpPayload) {
  return httpPost<MpAccount>('/mp-accounts', payload)
}
export function apiUpdateMpAccount(id: number, payload: Partial<MpAccount>) {
  return httpPut<MpAccount>(`/mp-accounts/${id}`, payload)
}
export interface VerifyResult {
  ok: boolean
  checked?: string
  hint?: string
  [key: string]: unknown
}
export function apiVerifyMpAccount(id: number) {
  return httpPost<VerifyResult>(`/mp-accounts/${id}/verify`)
}
// 浏览器发布登录态授权:状态查询 + 手动吊销(续扫入口)
export function apiGetLoginAuth(id: number) {
  return httpGet<LoginAuthStatus>(`/mp-accounts/${id}/login-auth`)
}
export function apiRevokeLoginAuth(id: number) {
  return httpPost<{ ok: boolean; wx_login_status?: string; hint?: string }>(
    `/mp-accounts/${id}/login-revoke`,
  )
}
export function apiGetAssignees(id: number) {
  return httpGet<Assignee[]>(`/mp-accounts/${id}/assignees`)
}
// 全量覆盖提交(后端要 {assignments:[{user_id, perm_level:1-4}]})
export function apiSetAssignees(
  id: number,
  assignments: Array<{ user_id: number; perm_level: number }>,
) {
  return httpPut<null>(`/mp-accounts/${id}/assignees`, { assignments })
}

// -------- Audit --------
export interface AuditListQuery {
  page?: number
  page_size?: number
  keyword?: string
}
export function apiListAudit(query: AuditListQuery = {}) {
  return httpGet<PageResult<AuditRecord>>('/audit-records', { params: query })
}

// ==================== M2 内容中心 ====================

// -------- Materials (素材库) --------
export interface MaterialListQuery {
  page?: number
  page_size?: number
  keyword?: string
  type?: string
  mp_account_id?: number
}
export function apiListMaterials(query: MaterialListQuery = {}) {
  return httpGet<PageResult<Material>>('/materials', { params: query })
}
// multipart 上传; onProgress 可选进度回调
export function apiUploadMaterial(
  file: File,
  extra?: { mp_account_id?: number; type?: string },
  onProgress?: (percent: number) => void,
) {
  const fd = new FormData()
  fd.append('file', file)
  if (extra?.mp_account_id != null) fd.append('mp_account_id', String(extra.mp_account_id))
  if (extra?.type) fd.append('type', extra.type)
  return httpPost<Material>('/materials', fd, {
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress: (e) => {
      if (onProgress && e.total) onProgress(Math.round((e.loaded * 100) / e.total))
    },
  })
}
export function apiDeleteMaterial(id: number) {
  return httpDelete<null>(`/materials/${id}`)
}

// -------- Style Templates (样式模板) --------
export function apiListStyleTemplates() {
  return httpGet<StyleTemplate[]>('/style-templates')
}

// -------- Articles (图文) --------
export interface ArticleListQuery {
  page?: number
  page_size?: number
  keyword?: string
  status?: ArticleStatus
  mp_account_id?: number
}
export function apiListArticles(query: ArticleListQuery = {}) {
  return httpGet<PageResult<Article>>('/articles', { params: query })
}
export function apiGetArticle(id: number) {
  return httpGet<Article>(`/articles/${id}`)
}
export interface ArticlePayload {
  mp_account_id?: number
  title: string
  author?: string
  digest?: string
  content_html?: string
  cover_material_id?: number
  style_template_id?: number
  content_source_url?: string
  need_open_comment?: number
  only_fans_can_comment?: number
  [key: string]: unknown
}
export function apiCreateArticle(payload: ArticlePayload) {
  return httpPost<Article>('/articles', payload)
}
export function apiUpdateArticle(id: number, payload: Partial<ArticlePayload>) {
  return httpPut<Article>(`/articles/${id}`, payload)
}
export function apiSubmitArticle(id: number) {
  return httpPost<Article>(`/articles/${id}/submit`)
}
// result: 'pass' | 'reject'
export function apiAuditArticle(id: number, result: 'pass' | 'reject', opinion?: string) {
  return httpPost<Article>(`/articles/${id}/audit`, { result, opinion })
}
export function apiListArticleVersions(id: number) {
  return httpGet<ArticleVersion[]>(`/articles/${id}/versions`)
}
export function apiCreateArticleVersion(id: number, changeNote?: string) {
  return httpPost<ArticleVersion>(`/articles/${id}/versions`, { change_note: changeNote ?? '' })
}
export function apiRollbackArticle(id: number, versionNo: number) {
  return httpPost<Article>(`/articles/${id}/rollback`, { version_no: versionNo })
}

// -------- Draft Groups (多图文组) --------
export interface CreateDraftGroupPayload {
  group_name?: string
  mp_account_id?: number
}
export function apiCreateDraftGroup(payload: CreateDraftGroupPayload = {}) {
  return httpPost<DraftGroup>('/draft-groups', payload)
}
export function apiGetDraftGroup(id: number) {
  return httpGet<DraftGroup>(`/draft-groups/${id}`)
}
export function apiAddDraftGroupArticle(id: number, articleId: number) {
  return httpPost<DraftGroup>(`/draft-groups/${id}/articles`, { article_id: articleId })
}
// article_ids: 有序 article_id 数组 (后端为 PATCH)
export function apiReorderDraftGroup(id: number, articleIds: number[]) {
  return httpPatch<DraftGroup>(`/draft-groups/${id}/reorder`, { article_ids: articleIds })
}

// -------- Publish (发布任务) --------
export interface PublishTaskListQuery {
  page?: number
  page_size?: number
  status?: string
  mp_account_id?: number
  keyword?: string
}
export function apiListPublishTasks(query: PublishTaskListQuery = {}) {
  return httpGet<PageResult<PublishTask>>('/publish/tasks', { params: query })
}
export function apiGetPublishTask(id: number) {
  return httpGet<PublishTask>(`/publish/tasks/${id}`)
}
export interface CreatePublishTaskPayload {
  content_article_id?: number
  draft_group_id?: number
  mp_account_id: number
  scheduled_at?: string
}
export function apiCreatePublishTask(payload: CreatePublishTaskPayload) {
  return httpPost<PublishTask>('/publish/tasks', payload)
}
export function apiCancelPublishTask(id: number) {
  return httpPost<PublishTask>(`/publish/tasks/${id}/cancel`)
}
export function apiRetryPublishTask(id: number) {
  return httpPost<PublishTask>(`/publish/tasks/${id}/retry`)
}
// 一键下架已发布文章(权限 publish:task:manage)
export function apiTakedownPublishTask(id: number) {
  return httpPost<PublishTask>(`/publish/tasks/${id}/takedown`)
}
export function apiGetPublishTaskLogs(id: number) {
  return httpGet<PublishLog[]>(`/publish/tasks/${id}/logs`)
}
export function apiGetPublishStats() {
  return httpGet<PublishStats>('/publish/stats')
}

// -------- Scheduler (M4 调度 / 运营看板) --------
// 手动触发一次全自动流水线(权限 system:config:manage)
export function apiSchedulerTick() {
  return httpPost<SchedulerTickResult>('/scheduler/tick')
}
// 运营看板数据(权限 publish:task:view)
export function apiSchedulerDashboard() {
  return httpGet<SchedulerDashboard>('/scheduler/dashboard')
}

// ==================== M3 采集中心 ====================

// -------- 采集源 (collect/sources) --------
export interface CollectSourceListQuery {
  page?: number
  page_size?: number
  keyword?: string
  adapter_type?: string
  status?: string
}
export function apiListCollectSources(query: CollectSourceListQuery = {}) {
  return httpGet<PageResult<CollectSource>>('/collect/sources', { params: query })
}
export function apiGetCollectSource(id: number) {
  return httpGet<CollectSource>(`/collect/sources/${id}`)
}
export interface CollectSourcePayload {
  source_name: string
  adapter_type: string
  config_json?: string
  interval_minutes?: number
  jitter_seconds?: number
  whitelist_confirmed?: boolean
  auth_proof_url?: string
  [key: string]: unknown
}
// 后端 config_json 需为对象、whitelist_confirmed 需为整数;这里做归一化容错
function normalizeSourcePayload(p: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = { ...p }
  if (typeof out.config_json === 'string') {
    const s = (out.config_json as string).trim()
    out.config_json = s ? JSON.parse(s) : {}
  }
  if (typeof out.whitelist_confirmed === 'boolean') {
    out.whitelist_confirmed = out.whitelist_confirmed ? 1 : 0
  }
  return out
}
export function apiCreateCollectSource(payload: CollectSourcePayload) {
  return httpPost<CollectSource>('/collect/sources', normalizeSourcePayload(payload))
}
export function apiUpdateCollectSource(id: number, payload: Partial<CollectSourcePayload>) {
  return httpPut<CollectSource>(`/collect/sources/${id}`, normalizeSourcePayload(payload))
}
export function apiDeleteCollectSource(id: number) {
  return httpDelete<null>(`/collect/sources/${id}`)
}
export function apiEnableCollectSource(id: number) {
  return httpPost<CollectSource>(`/collect/sources/${id}/enable`)
}
export function apiDisableCollectSource(id: number) {
  return httpPost<CollectSource>(`/collect/sources/${id}/disable`)
}
// 试运行: 返回样例, 不落库
export function apiTestRunCollectSource(id: number) {
  return httpPost<CollectRunResult>(`/collect/sources/${id}/test-run`)
}
// 立即采集: 返回 collected/duplicated
export function apiRunNowCollectSource(id: number) {
  return httpPost<CollectRunResult>(`/collect/sources/${id}/run-now`)
}

// -------- 手动导入 (collect/manual-import) --------
export interface ManualImportPayload {
  source_id: number
  title: string
  author?: string
  url?: string
  raw_html: string
  is_original_marked?: number
  [key: string]: unknown
}
export function apiManualImport(payload: ManualImportPayload) {
  return httpPost<CollectArticle>('/collect/manual-import', payload)
}

// -------- 采集文章 (collect/articles) --------
export interface CollectArticleListQuery {
  page?: number
  page_size?: number
  keyword?: string
  status?: CollectArticleStatus
  source_id?: number
}
export function apiListCollectArticles(query: CollectArticleListQuery = {}) {
  return httpGet<PageResult<CollectArticle>>('/collect/articles', { params: query })
}
export function apiGetCollectArticle(id: number) {
  return httpGet<CollectArticle>(`/collect/articles/${id}`)
}
export function apiGetCollectArticleDedupInfo(id: number) {
  return httpGet<DedupInfo>(`/collect/articles/${id}/dedup-info`)
}
export function apiDeleteCollectArticle(id: number) {
  return httpDelete<null>(`/collect/articles/${id}`)
}

// -------- 采集总览 (collect/stats/overview) --------
export function apiGetCollectOverview() {
  return httpGet<CollectOverview>('/collect/stats/overview')
}

// ==================== M3 映射规则 ====================

// -------- 映射规则 (mapping/rules) --------
export interface MappingRuleListQuery {
  page?: number
  page_size?: number
  keyword?: string
  enabled?: boolean
  target_mp_account_id?: number
}
export function apiListMappingRules(query: MappingRuleListQuery = {}) {
  return httpGet<PageResult<MappingRule>>('/mapping/rules', { params: query })
}
export function apiGetMappingRule(id: number) {
  return httpGet<MappingRule>(`/mapping/rules/${id}`)
}
// JSON 字段为对象、enabled 为整数(对齐后端)
export interface MappingRulePayload {
  rule_name: string
  target_mp_account_id: number
  source_ids: number[]
  priority?: number
  enabled?: number
  match_condition_json?: Record<string, unknown>
  transform_action_json?: Record<string, unknown>
  schedule_policy_json?: Record<string, unknown>
  [key: string]: unknown
}
export function apiCreateMappingRule(payload: MappingRulePayload) {
  return httpPost<MappingRule>('/mapping/rules', payload)
}
export function apiUpdateMappingRule(id: number, payload: MappingRulePayload) {
  return httpPut<MappingRule>(`/mapping/rules/${id}`, payload)
}
export function apiDeleteMappingRule(id: number) {
  return httpDelete<null>(`/mapping/rules/${id}`)
}
// 启停切换 (后端 PATCH status,enabled 为整数 0/1)
export function apiSetMappingRuleStatus(id: number, enabled: boolean) {
  return httpPatch<MappingRule>(`/mapping/rules/${id}/status`, { enabled: enabled ? 1 : 0 })
}
// 条件试算(后端: {match_condition_json, sample:{title,content}})
export function apiMappingDryRun(matchCondition: Record<string, unknown>, sample: { title: string; content?: string }) {
  return httpPost<MappingDryRunResult>('/mapping/rules/dry-run', {
    match_condition_json: matchCondition,
    sample,
  })
}
// 单规则转换预览(后端: {collect_article_id})
export function apiMappingRulePreview(id: number, collectArticleId: number) {
  return httpPost<{ title: string; content_html: string }>(`/mapping/rules/${id}/preview`, {
    collect_article_id: collectArticleId,
  })
}
// 处理待映射
export function apiMappingRunPending() {
  return httpPost<MappingRunPendingResult>('/mapping/run-pending')
}
// 执行记录
export interface MappingExecutionListQuery {
  page?: number
  page_size?: number
  rule_id?: number
  result?: string
}
export function apiListMappingExecutions(query: MappingExecutionListQuery = {}) {
  return httpGet<PageResult<MappingExecution>>('/mapping/executions', { params: query })
}
