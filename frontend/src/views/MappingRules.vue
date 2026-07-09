<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import {
  apiCreateMappingRule,
  apiDeleteMappingRule,
  apiListCollectSources,
  apiListMappingRules,
  apiListMpAccounts,
  apiMappingDryRun,
  apiSetMappingRuleStatus,
  apiUpdateMappingRule,
  type MappingRulePayload,
} from '@/api/modules'
import { useAuthStore } from '@/stores/auth'
import type { CollectSource, MappingRule, MpAccount } from '@/api/types'

const auth = useAuthStore()
const canManage = auth.hasPerm('mapping:rule:manage')

const loading = ref(false)
const list = ref<MappingRule[]>([])
const total = ref(0)
const query = reactive({ page: 1, page_size: 10, keyword: '' })

const mpAccounts = ref<MpAccount[]>([])
const sources = ref<CollectSource[]>([])
function mpName(id?: number) {
  return mpAccounts.value.find((m) => m.id === id)?.mp_name || (id != null ? `#${id}` : '-')
}

async function loadRefs() {
  const [mps, srcs] = await Promise.all([
    apiListMpAccounts({ page: 1, page_size: 100 }),
    apiListCollectSources({ page: 1, page_size: 100 }),
  ])
  mpAccounts.value = mps.items
  sources.value = srcs.items
}
async function loadList() {
  loading.value = true
  try {
    const data = await apiListMappingRules({
      page: query.page,
      page_size: query.page_size,
      keyword: query.keyword || undefined,
    })
    list.value = data.items
    total.value = data.total
  } finally {
    loading.value = false
  }
}
function onSearch() {
  query.page = 1
  loadList()
}

// ---------------- 新建 / 编辑 ----------------
const dialogVisible = ref(false)
const editMode = ref<'create' | 'edit'>('create')
const editId = ref(0)
const formRef = ref<FormInstance>()
const form = reactive({
  rule_name: '',
  target_mp_account_id: undefined as number | undefined,
  source_ids: [] as number[],
  priority: 100,
  enabled: true,
  // match_condition
  keywords_include: [] as string[],
  include_mode: 'ANY',
  keywords_exclude: [] as string[],
  match_field: 'title_and_content',
  min_word_count: 0,
  // transform
  title_template: '【转】{title}',
  source_note: '<hr/><p style="color:#888;font-size:13px">本文转载自「{source_name}」,原文《{title}》,版权归原作者所有。</p>',
  // schedule
  window_start: '19:00',
  daily_limit: 2,
})
const rules: FormRules = {
  rule_name: [{ required: true, message: '请输入规则名', trigger: 'blur' }],
  target_mp_account_id: [{ required: true, message: '请选择目标公众号', trigger: 'change' }],
  source_ids: [{ required: true, type: 'array', min: 1, message: '至少选择一个采集源', trigger: 'change' }],
}

function resetForm() {
  Object.assign(form, {
    rule_name: '', target_mp_account_id: undefined, source_ids: [], priority: 100, enabled: true,
    keywords_include: [], include_mode: 'ANY', keywords_exclude: [], match_field: 'title_and_content',
    min_word_count: 0, title_template: '【转】{title}',
    source_note: '<hr/><p style="color:#888;font-size:13px">本文转载自「{source_name}」,原文《{title}》,版权归原作者所有。</p>',
    window_start: '19:00', daily_limit: 2,
  })
}
function openCreate() {
  editMode.value = 'create'
  editId.value = 0
  resetForm()
  dialogVisible.value = true
}
function openEdit(row: MappingRule) {
  editMode.value = 'edit'
  editId.value = row.id
  resetForm()
  const cond = (row.match_condition_json as unknown as Record<string, unknown>) || {}
  const act = (row.transform_action_json as unknown as Record<string, unknown>) || {}
  const sch = (row.schedule_policy_json as unknown as Record<string, unknown>) || {}
  Object.assign(form, {
    rule_name: row.rule_name,
    target_mp_account_id: row.target_mp_account_id,
    source_ids: [...(row.source_ids || [])],
    priority: row.priority ?? 100,
    enabled: Boolean(row.enabled),
    keywords_include: (cond.keywords_include as string[]) || [],
    include_mode: (cond.keywords_include_mode as string) || 'ANY',
    keywords_exclude: (cond.keywords_exclude as string[]) || [],
    match_field: (cond.match_field as string) || 'title_and_content',
    min_word_count: (cond.min_word_count as number) || 0,
    title_template: (act.title_template as string) || '{title}',
  })
  const win = (sch.time_windows as Array<{ start?: string }>) || []
  form.window_start = win[0]?.start || ''
  form.daily_limit = (sch.daily_limit as number) || 0
  dialogVisible.value = true
}

function buildPayload(): MappingRulePayload {
  const match_condition_json: Record<string, unknown> = {
    match_field: form.match_field,
    keywords_include_mode: form.include_mode,
  }
  if (form.keywords_include.length) match_condition_json.keywords_include = form.keywords_include
  if (form.keywords_exclude.length) match_condition_json.keywords_exclude = form.keywords_exclude
  if (form.min_word_count > 0) match_condition_json.min_word_count = form.min_word_count

  const body_pipeline: Array<Record<string, unknown>> = [{ type: 'rehost_images', mode: 'mark_only' }]
  if (form.source_note.trim()) {
    body_pipeline.push({ type: 'append_block', position: 'tail', template: form.source_note })
  }
  const transform_action_json = { title_template: form.title_template || '{title}', body_pipeline }

  const schedule_policy_json: Record<string, unknown> = { overflow: 'NEXT_DAY' }
  if (form.window_start.trim()) schedule_policy_json.time_windows = [{ start: form.window_start.trim() }]
  if (form.daily_limit > 0) schedule_policy_json.daily_limit = form.daily_limit

  return {
    rule_name: form.rule_name,
    target_mp_account_id: form.target_mp_account_id as number,
    source_ids: form.source_ids,
    priority: form.priority,
    enabled: form.enabled ? 1 : 0,
    match_condition_json,
    transform_action_json,
    schedule_policy_json,
  }
}

const saving = ref(false)
async function submit() {
  if (!formRef.value) return
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return
  saving.value = true
  try {
    const payload = buildPayload()
    if (editMode.value === 'create') {
      await apiCreateMappingRule(payload)
      ElMessage.success('规则已创建')
    } else {
      await apiUpdateMappingRule(editId.value, payload)
      ElMessage.success('规则已更新')
    }
    dialogVisible.value = false
    loadList()
  } finally {
    saving.value = false
  }
}

async function onToggle(row: MappingRule) {
  const next = !row.enabled
  await apiSetMappingRuleStatus(row.id, next)
  ElMessage.success(next ? '已启用' : '已停用')
  loadList()
}
async function onDelete(row: MappingRule) {
  await ElMessageBox.confirm(`确认删除规则「${row.rule_name}」?`, '提示', { type: 'warning' })
  await apiDeleteMappingRule(row.id)
  ElMessage.success('已删除')
  loadList()
}

// ---------------- 条件试算 ----------------
const dryVisible = ref(false)
const drySample = reactive({ title: '', content: '' })
const dryResult = ref<Record<string, unknown> | null>(null)
function openDryRun() {
  drySample.title = ''
  drySample.content = ''
  dryResult.value = null
  dryVisible.value = true
}
async function runDry() {
  const cond = buildPayload().match_condition_json || {}
  dryResult.value = (await apiMappingDryRun(cond, { title: drySample.title, content: drySample.content })) as Record<string, unknown>
}

const dryChecks = computed(() => (dryResult.value?.checks as Array<Record<string, unknown>>) || [])

onMounted(() => {
  loadRefs()
  loadList()
})
</script>

<template>
  <div class="page-container">
    <div class="page-toolbar">
      <div class="left">
        <el-input v-model="query.keyword" placeholder="搜索规则名" clearable style="width: 220px" @keyup.enter="onSearch" />
        <el-button type="primary" @click="onSearch"><el-icon><Search /></el-icon>搜索</el-button>
      </div>
      <div class="right">
        <el-button v-if="canManage" type="primary" @click="openCreate"><el-icon><Plus /></el-icon>新建规则</el-button>
      </div>
    </div>

    <el-table v-loading="loading" :data="list" border stripe>
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column prop="rule_name" label="规则名" min-width="160" />
      <el-table-column label="目标公众号" min-width="140">
        <template #default="{ row }">{{ mpName((row as MappingRule).target_mp_account_id) }}</template>
      </el-table-column>
      <el-table-column label="关联源" width="90" align="center">
        <template #default="{ row }">{{ ((row as MappingRule).source_ids || []).length }}</template>
      </el-table-column>
      <el-table-column prop="priority" label="优先级" width="90" align="center" />
      <el-table-column label="启用" width="90" align="center">
        <template #default="{ row }">
          <el-switch
            :model-value="Boolean((row as MappingRule).enabled)"
            :disabled="!canManage"
            @click="onToggle(row as MappingRule)"
          />
        </template>
      </el-table-column>
      <el-table-column label="操作" width="180" fixed="right">
        <template #default="{ row }">
          <el-button v-if="canManage" link type="primary" @click="openEdit(row as MappingRule)">编辑</el-button>
          <el-button v-if="canManage" link type="danger" @click="onDelete(row as MappingRule)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <div class="pager">
      <el-pagination
        v-model:current-page="query.page"
        v-model:page-size="query.page_size"
        :total="total"
        :page-sizes="[10, 20, 50]"
        layout="total, sizes, prev, pager, next, jumper"
        background
        @current-change="loadList"
        @size-change="onSearch"
      />
    </div>

    <!-- 新建 / 编辑 -->
    <el-dialog v-model="dialogVisible" :title="editMode === 'create' ? '新建映射规则' : '编辑映射规则'" width="720px" top="5vh">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="110px">
        <el-divider content-position="left">基本</el-divider>
        <el-form-item label="规则名" prop="rule_name">
          <el-input v-model="form.rule_name" placeholder="如:科技三源→AI观察" />
        </el-form-item>
        <el-form-item label="目标公众号" prop="target_mp_account_id">
          <el-select v-model="form.target_mp_account_id" placeholder="选择自有公众号" style="width: 100%">
            <el-option v-for="m in mpAccounts" :key="m.id" :label="m.mp_name" :value="m.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="采集源" prop="source_ids">
          <el-select v-model="form.source_ids" multiple placeholder="选择一个或多个采集源" style="width: 100%">
            <el-option v-for="s in sources" :key="s.id" :label="s.source_name" :value="s.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="优先级">
          <el-input-number v-model="form.priority" :min="0" :max="9999" />
          <span class="hint">数值越大越优先,同目标号只保留最高一条</span>
        </el-form-item>

        <el-divider content-position="left">筛选条件</el-divider>
        <el-form-item label="包含关键词">
          <el-select v-model="form.keywords_include" multiple filterable allow-create default-first-option placeholder="回车添加" style="width: 100%" />
        </el-form-item>
        <el-form-item label="包含模式">
          <el-radio-group v-model="form.include_mode">
            <el-radio value="ANY">含任一</el-radio>
            <el-radio value="ALL">须全含</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="排除关键词">
          <el-select v-model="form.keywords_exclude" multiple filterable allow-create default-first-option placeholder="命中任一即不采用" style="width: 100%" />
        </el-form-item>
        <el-form-item label="匹配范围">
          <el-select v-model="form.match_field" style="width: 200px">
            <el-option label="标题+正文" value="title_and_content" />
            <el-option label="仅标题" value="title" />
            <el-option label="仅正文" value="content" />
          </el-select>
          <span class="hint">最小字数</span>
          <el-input-number v-model="form.min_word_count" :min="0" :max="99999" />
        </el-form-item>

        <el-divider content-position="left">转换动作</el-divider>
        <el-form-item label="标题模板">
          <el-input v-model="form.title_template" placeholder="占位: {title} {source_name} {date}" />
        </el-form-item>
        <el-form-item label="来源声明">
          <el-input v-model="form.source_note" type="textarea" :rows="2" placeholder="转载来源与版权声明(尾部追加)" />
        </el-form-item>
        <el-alert type="info" :closable="false" class="mb" show-icon>
          正文外链图片仅"标记待转存",实际转存在内容中心提审时统一执行(不在此上传)。
        </el-alert>

        <el-divider content-position="left">排期策略</el-divider>
        <el-form-item label="发布时间窗">
          <el-input v-model="form.window_start" placeholder="HH:MM,如 19:00" style="width: 160px" />
          <span class="hint">每日限量</span>
          <el-input-number v-model="form.daily_limit" :min="0" :max="50" />
          <span class="hint">超额顺延次日</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="openDryRun">条件试算</el-button>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submit">确定</el-button>
      </template>
    </el-dialog>

    <!-- 条件试算 -->
    <el-dialog v-model="dryVisible" title="条件试算" width="560px">
      <el-form label-width="70px">
        <el-form-item label="样例标题"><el-input v-model="drySample.title" /></el-form-item>
        <el-form-item label="样例正文"><el-input v-model="drySample.content" type="textarea" :rows="3" /></el-form-item>
      </el-form>
      <el-button type="primary" @click="runDry">试算当前条件</el-button>
      <div v-if="dryResult" class="dry-result">
        <el-tag :type="dryResult.matched ? 'success' : 'danger'" size="large">
          {{ dryResult.matched ? '命中' : '未命中' }}
        </el-tag>
        <el-table :data="dryChecks" border size="small" class="mt">
          <el-table-column prop="name" label="关卡" width="150" />
          <el-table-column label="通过" width="80" align="center">
            <template #default="{ row }">
              <el-tag :type="row.passed ? 'success' : 'danger'" size="small">{{ row.passed ? '✓' : '✗' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="detail" label="说明" min-width="180" />
        </el-table>
      </div>
    </el-dialog>
  </div>
</template>

<style scoped>
.pager { margin-top: 16px; display: flex; justify-content: flex-end; }
.hint { color: #909399; font-size: 12px; margin: 0 8px; }
.mb { margin-bottom: 12px; }
.mt { margin-top: 12px; }
.dry-result { margin-top: 16px; }
</style>
