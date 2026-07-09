<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import {
  apiCreateCollectSource,
  apiDeleteCollectSource,
  apiDisableCollectSource,
  apiEnableCollectSource,
  apiListCollectSources,
  apiRunNowCollectSource,
  apiTestRunCollectSource,
  apiUpdateCollectSource,
  type CollectSourcePayload,
} from '@/api/modules'
import { useAuthStore } from '@/stores/auth'
import type { CollectRunResult, CollectSource } from '@/api/types'

const auth = useAuthStore()
const canManage = computed(
  () => auth.hasPerm('collect:source:manage') || auth.hasPerm('user:manage'),
)

const ADAPTER_TYPES: Array<{ value: string; label: string }> = [
  { value: 'mock', label: '模拟源(Mock,本地样例)' },
  { value: 'rss', label: 'RSS 订阅源' },
  { value: 'manual', label: '手工导入' },
]
const ADAPTER_META: Record<string, { label: string; type: 'info' | 'primary' | 'success' }> = {
  mock: { label: 'Mock', type: 'info' },
  rss: { label: 'RSS', type: 'primary' },
  manual: { label: '手工', type: 'success' },
}
function adapterMeta(t: string) {
  return ADAPTER_META[t] || { label: t || '-', type: 'info' as const }
}

const STATUS_OPTIONS: Array<{ value: string; label: string }> = [
  { value: 'ACTIVE', label: '运行中' },
  { value: 'PAUSED', label: '已暂停' },
  { value: 'CIRCUIT_OPEN', label: '熔断' },
]
const STATUS_META: Record<
  string,
  { label: string; type: 'info' | 'warning' | 'success' | 'danger' }
> = {
  ACTIVE: { label: '运行中', type: 'success' },
  PAUSED: { label: '已暂停', type: 'info' },
  CIRCUIT_OPEN: { label: '熔断', type: 'danger' },
}
function statusMeta(s: string) {
  return STATUS_META[s] || { label: s || '-', type: 'info' as const }
}

// ---------- 列表 ----------
const loading = ref(false)
const list = ref<CollectSource[]>([])
const total = ref(0)
const query = reactive<{
  page: number
  page_size: number
  keyword: string
  adapter_type?: string
  status?: string
}>({ page: 1, page_size: 10, keyword: '', adapter_type: undefined, status: undefined })

async function loadList() {
  loading.value = true
  try {
    const data = await apiListCollectSources({
      page: query.page,
      page_size: query.page_size,
      keyword: query.keyword || undefined,
      adapter_type: query.adapter_type || undefined,
      status: query.status || undefined,
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
function onReset() {
  query.keyword = ''
  query.adapter_type = undefined
  query.status = undefined
  query.page = 1
  loadList()
}

// ---------- 新建 / 编辑 ----------
const editVisible = ref(false)
const editMode = ref<'create' | 'edit'>('create')
const editForm = reactive<{
  id: number
  source_name: string
  adapter_type: string
  feed_url: string
  dataset: string
  config_json: string
  config_mode: 'form' | 'json'
  interval_minutes: number
  jitter_seconds: number
  whitelist_confirmed: boolean
  auth_proof_url: string
}>({
  id: 0,
  source_name: '',
  adapter_type: 'mock',
  feed_url: '',
  dataset: '',
  config_json: '',
  config_mode: 'form',
  interval_minutes: 60,
  jitter_seconds: 30,
  whitelist_confirmed: false,
  auth_proof_url: '',
})
const editFormRef = ref<FormInstance>()
const editRules: FormRules = {
  source_name: [{ required: true, message: '请输入采集源名称', trigger: 'blur' }],
  adapter_type: [{ required: true, message: '请选择适配器类型', trigger: 'change' }],
}

function resetEditForm() {
  Object.assign(editForm, {
    id: 0,
    source_name: '',
    adapter_type: 'mock',
    feed_url: '',
    dataset: '',
    config_json: '',
    config_mode: 'form',
    interval_minutes: 60,
    jitter_seconds: 30,
    whitelist_confirmed: false,
    auth_proof_url: '',
  })
}

function openCreate() {
  editMode.value = 'create'
  resetEditForm()
  editVisible.value = true
}
function openEdit(row: CollectSource) {
  editMode.value = 'edit'
  resetEditForm()
  editForm.id = row.id
  editForm.source_name = row.source_name
  editForm.adapter_type = row.adapter_type || 'mock'
  editForm.interval_minutes = row.interval_minutes ?? 60
  editForm.jitter_seconds = row.jitter_seconds ?? 30
  editForm.whitelist_confirmed = !!row.whitelist_confirmed
  editForm.auth_proof_url = row.auth_proof_url || ''
  editForm.config_json = row.config_json || ''
  // 尝试把已存 config_json 拆回结构化字段
  if (row.config_json) {
    try {
      const cfg = JSON.parse(row.config_json) as Record<string, unknown>
      editForm.feed_url = typeof cfg.feed_url === 'string' ? cfg.feed_url : ''
      editForm.dataset = typeof cfg.dataset === 'string' ? cfg.dataset : ''
    } catch {
      // 无法解析则切到 JSON 模式让用户直接编辑
      editForm.config_mode = 'json'
    }
  }
  editVisible.value = true
}

// 依据当前表单构造 config_json 字符串
function buildConfigJson(): string | undefined {
  if (editForm.config_mode === 'json') {
    const raw = editForm.config_json.trim()
    if (!raw) return undefined
    return raw
  }
  const cfg: Record<string, unknown> = {}
  if (editForm.adapter_type === 'rss' && editForm.feed_url.trim()) {
    cfg.feed_url = editForm.feed_url.trim()
  }
  if (editForm.adapter_type === 'mock' && editForm.dataset.trim()) {
    cfg.dataset = editForm.dataset.trim()
  }
  return Object.keys(cfg).length ? JSON.stringify(cfg) : undefined
}

const saving = ref(false)
async function submitEdit() {
  if (!editFormRef.value) return
  const valid = await editFormRef.value.validate().catch(() => false)
  if (!valid) return
  // JSON 模式校验合法性
  let configJson: string | undefined
  if (editForm.config_mode === 'json' && editForm.config_json.trim()) {
    try {
      JSON.parse(editForm.config_json)
    } catch {
      ElMessage.error('配置 JSON 格式不合法')
      return
    }
    configJson = editForm.config_json.trim()
  } else {
    configJson = buildConfigJson()
  }

  const payload: CollectSourcePayload = {
    source_name: editForm.source_name,
    adapter_type: editForm.adapter_type,
    config_json: configJson,
    interval_minutes: editForm.interval_minutes,
    jitter_seconds: editForm.jitter_seconds,
    whitelist_confirmed: editForm.whitelist_confirmed,
    auth_proof_url: editForm.auth_proof_url || undefined,
  }
  saving.value = true
  try {
    if (editMode.value === 'create') {
      await apiCreateCollectSource(payload)
      ElMessage.success('创建成功')
    } else {
      await apiUpdateCollectSource(editForm.id, payload)
      ElMessage.success('更新成功')
    }
    editVisible.value = false
    loadList()
  } finally {
    saving.value = false
  }
}

// ---------- 启停 ----------
const busyId = ref<number | null>(null)
async function onToggle(row: CollectSource) {
  busyId.value = row.id
  try {
    if (row.status === 'ACTIVE') {
      await apiDisableCollectSource(row.id)
      ElMessage.success('已暂停')
    } else {
      await apiEnableCollectSource(row.id)
      ElMessage.success('已启用')
    }
    loadList()
  } finally {
    busyId.value = null
  }
}

// ---------- test-run / run-now 结果 ----------
const runVisible = ref(false)
const runMode = ref<'test' | 'now'>('test')
const runResult = ref<CollectRunResult | null>(null)
const runSourceName = ref('')

async function onTestRun(row: CollectSource) {
  busyId.value = row.id
  runMode.value = 'test'
  runSourceName.value = row.source_name
  try {
    runResult.value = await apiTestRunCollectSource(row.id)
    runVisible.value = true
  } finally {
    busyId.value = null
  }
}
async function onRunNow(row: CollectSource) {
  busyId.value = row.id
  runMode.value = 'now'
  runSourceName.value = row.source_name
  try {
    runResult.value = await apiRunNowCollectSource(row.id)
    runVisible.value = true
    loadList() // 立即采集后 fail_count / status 可能变化
  } finally {
    busyId.value = null
  }
}

// ---------- 删除 ----------
async function onDelete(row: CollectSource) {
  try {
    await ElMessageBox.confirm(`确定删除采集源「${row.source_name}」?`, '删除采集源', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  busyId.value = row.id
  try {
    await apiDeleteCollectSource(row.id)
    ElMessage.success('已删除')
    loadList()
  } finally {
    busyId.value = null
  }
}

onMounted(loadList)
</script>

<template>
  <div class="page-container">
    <div class="page-toolbar">
      <div class="left">
        <el-input
          v-model="query.keyword"
          placeholder="搜索采集源名称"
          clearable
          style="width: 200px"
          @keyup.enter="onSearch"
          @clear="onSearch"
        />
        <el-select
          v-model="query.adapter_type"
          placeholder="类型"
          clearable
          style="width: 140px"
          @change="onSearch"
        >
          <el-option
            v-for="a in ADAPTER_TYPES"
            :key="a.value"
            :label="a.label"
            :value="a.value"
          />
        </el-select>
        <el-select
          v-model="query.status"
          placeholder="状态"
          clearable
          style="width: 130px"
          @change="onSearch"
        >
          <el-option
            v-for="s in STATUS_OPTIONS"
            :key="s.value"
            :label="s.label"
            :value="s.value"
          />
        </el-select>
        <el-button type="primary" @click="onSearch">
          <el-icon><Search /></el-icon>搜索
        </el-button>
        <el-button @click="onReset">重置</el-button>
      </div>
      <div class="right">
        <el-button v-if="canManage" type="primary" @click="openCreate">
          <el-icon><Plus /></el-icon>新建采集源
        </el-button>
      </div>
    </div>

    <el-table v-loading="loading" :data="list" border stripe>
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column prop="source_name" label="采集源名称" min-width="180" show-overflow-tooltip />
      <el-table-column label="类型" width="100" align="center">
        <template #default="{ row }">
          <el-tag :type="adapterMeta(row.adapter_type).type" size="small">
            {{ adapterMeta(row.adapter_type).label }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="100" align="center">
        <template #default="{ row }">
          <el-tag :type="statusMeta(row.status).type" size="small" effect="dark">
            {{ statusMeta(row.status).label }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="采集间隔" width="140" align="center">
        <template #default="{ row }">
          <span v-if="row.interval_minutes">
            {{ row.interval_minutes }} 分
            <span v-if="row.jitter_seconds" class="muted">±{{ row.jitter_seconds }}s</span>
          </span>
          <span v-else class="muted">-</span>
        </template>
      </el-table-column>
      <el-table-column label="失败次数" width="100" align="center">
        <template #default="{ row }">
          <el-tag v-if="row.fail_count" type="danger" size="small">{{ row.fail_count }}</el-tag>
          <span v-else class="muted">0</span>
        </template>
      </el-table-column>
      <el-table-column label="授权确认" width="100" align="center">
        <template #default="{ row }">
          <el-tag :type="row.whitelist_confirmed ? 'success' : 'info'" size="small">
            {{ row.whitelist_confirmed ? '已确认' : '未确认' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="360" fixed="right">
        <template #default="{ row }">
          <el-button
            link
            type="info"
            :loading="busyId === (row as CollectSource).id"
            @click="onTestRun(row as CollectSource)"
          >
            试运行
          </el-button>
          <el-button
            v-if="canManage"
            link
            type="success"
            :loading="busyId === (row as CollectSource).id"
            @click="onRunNow(row as CollectSource)"
          >
            立即采集
          </el-button>
          <el-button
            v-if="canManage"
            link
            :type="(row as CollectSource).status === 'ACTIVE' ? 'warning' : 'primary'"
            :loading="busyId === (row as CollectSource).id"
            @click="onToggle(row as CollectSource)"
          >
            {{ (row as CollectSource).status === 'ACTIVE' ? '暂停' : '启用' }}
          </el-button>
          <el-button v-if="canManage" link type="primary" @click="openEdit(row as CollectSource)">
            编辑
          </el-button>
          <el-button
            v-if="canManage"
            link
            type="danger"
            :loading="busyId === (row as CollectSource).id"
            @click="onDelete(row as CollectSource)"
          >
            删除
          </el-button>
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
    <el-dialog
      v-model="editVisible"
      :title="editMode === 'create' ? '新建采集源' : '编辑采集源'"
      width="620px"
      top="6vh"
    >
      <el-form ref="editFormRef" :model="editForm" :rules="editRules" label-width="110px">
        <el-form-item label="采集源名称" prop="source_name">
          <el-input v-model="editForm.source_name" placeholder="采集源名称" />
        </el-form-item>
        <el-form-item label="适配器类型" prop="adapter_type">
          <el-select v-model="editForm.adapter_type" style="width: 100%">
            <el-option
              v-for="a in ADAPTER_TYPES"
              :key="a.value"
              :label="a.label"
              :value="a.value"
            />
          </el-select>
        </el-form-item>

        <!-- 配置: 结构化表单 / JSON 二选一 -->
        <el-form-item label="配置方式">
          <el-radio-group v-model="editForm.config_mode">
            <el-radio-button value="form">结构化</el-radio-button>
            <el-radio-button value="json">JSON</el-radio-button>
          </el-radio-group>
        </el-form-item>

        <template v-if="editForm.config_mode === 'form'">
          <el-form-item v-if="editForm.adapter_type === 'rss'" label="Feed URL">
            <el-input v-model="editForm.feed_url" placeholder="https://example.com/feed.xml" />
          </el-form-item>
          <el-form-item v-else-if="editForm.adapter_type === 'mock'" label="数据集">
            <el-input v-model="editForm.dataset" placeholder="模拟样例数据集名(可选)" />
          </el-form-item>
          <el-form-item v-else label="配置">
            <div class="form-hint">手工导入类型无需采集配置,文章由「采集文章」页手动导入。</div>
          </el-form-item>
        </template>
        <el-form-item v-else label="config_json">
          <el-input
            v-model="editForm.config_json"
            type="textarea"
            :rows="4"
            placeholder='{"feed_url": "https://..."}'
          />
        </el-form-item>

        <el-form-item label="采集间隔(分)">
          <el-input-number v-model="editForm.interval_minutes" :min="1" :max="10080" />
        </el-form-item>
        <el-form-item label="抖动(秒)">
          <el-input-number v-model="editForm.jitter_seconds" :min="0" :max="3600" />
          <span class="form-hint inline">随机延迟,避免固定节奏被风控。</span>
        </el-form-item>

        <el-divider content-position="left">原创转载授权登记</el-divider>
        <el-alert
          type="warning"
          :closable="false"
          show-icon
          class="auth-alert"
          title="微信无 API 可查他人白名单,须线下取得授权后手工确认。"
        />
        <el-form-item label="已获授权">
          <el-switch v-model="editForm.whitelist_confirmed" />
          <span class="form-hint inline">开启表示已线下取得原创方转载授权。</span>
        </el-form-item>
        <el-form-item label="授权凭证 URL">
          <el-input
            v-model="editForm.auth_proof_url"
            placeholder="授权书 / 邮件截图存档链接(可选)"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submitEdit">确定</el-button>
      </template>
    </el-dialog>

    <!-- test-run / run-now 结果 -->
    <el-dialog
      v-model="runVisible"
      :title="runMode === 'test' ? '试运行结果(样例,未落库)' : '采集结果'"
      width="640px"
      top="8vh"
    >
      <p class="dialog-sub">采集源: <b>{{ runSourceName }}</b></p>
      <el-descriptions v-if="runResult" :column="3" border size="small" class="run-desc">
        <el-descriptions-item label="采集">{{ runResult.collected ?? 0 }}</el-descriptions-item>
        <el-descriptions-item label="重复">{{ runResult.duplicated ?? 0 }}</el-descriptions-item>
        <el-descriptions-item label="未匹配">{{ runResult.unmatched ?? 0 }}</el-descriptions-item>
      </el-descriptions>
      <template v-if="runResult?.samples?.length">
        <el-divider content-position="left">样例文章</el-divider>
        <el-table :data="runResult.samples" border size="small" max-height="300">
          <el-table-column type="index" label="#" width="50" />
          <el-table-column prop="title" label="标题" min-width="200" show-overflow-tooltip />
          <el-table-column prop="author" label="作者" width="120">
            <template #default="{ row }">{{ row.author || '-' }}</template>
          </el-table-column>
          <el-table-column label="链接" width="80">
            <template #default="{ row }">
              <el-link v-if="row.url" :href="row.url" target="_blank" type="primary">打开</el-link>
              <span v-else class="muted">-</span>
            </template>
          </el-table-column>
        </el-table>
      </template>
      <el-empty
        v-else-if="!runResult?.collected"
        description="本次无新增文章"
        :image-size="60"
      />
      <template #footer>
        <el-button type="primary" @click="runVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.pager {
  margin-top: 16px;
  display: flex;
  justify-content: flex-end;
}
.muted {
  color: #909399;
}
.dialog-sub {
  margin: 0 0 16px;
  color: #606266;
}
.form-hint {
  font-size: 12px;
  line-height: 1.5;
  color: #909399;
}
.form-hint.inline {
  margin-left: 10px;
}
.auth-alert {
  margin-bottom: 16px;
}
.run-desc {
  margin-bottom: 8px;
}
</style>
