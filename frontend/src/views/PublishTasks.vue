<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  apiCancelPublishTask,
  apiGetPublishStats,
  apiGetPublishTaskLogs,
  apiListPublishTasks,
  apiRetryPublishTask,
  apiTakedownPublishTask,
} from '@/api/modules'
import { useAuthStore } from '@/stores/auth'
import type { PublishLog, PublishStats, PublishTask } from '@/api/types'

const auth = useAuthStore()
const canOperate = computed(
  () => auth.hasPerm('publish:task:operate') || auth.hasPerm('user:manage'),
)
const canManage = computed(
  () => auth.hasPerm('publish:task:manage') || auth.hasPerm('user:manage'),
)

const mpOptions = computed(() => auth.visibleMp)

const STATUS_OPTIONS = [
  { value: 'SCHEDULED', label: '待发布' },
  { value: 'PUBLISHING', label: '发布中' },
  { value: 'PUBLISHED', label: '已发布' },
  { value: 'FAILED', label: '失败' },
]
const STATUS_META: Record<
  string,
  { label: string; type: 'info' | 'warning' | 'success' | 'danger' | 'primary' }
> = {
  SCHEDULED: { label: '待发布', type: 'info' },
  PUBLISHING: { label: '发布中', type: 'warning' },
  PUBLISHED: { label: '已发布', type: 'success' },
  FAILED: { label: '失败', type: 'danger' },
}
function statusMeta(s: string) {
  return STATUS_META[s] || { label: s || '-', type: 'info' as const }
}

// ---------- 统计卡片 ----------
const stats = ref<PublishStats>({})
const statCards = computed(() => [
  { key: 'total', label: '总任务', value: stats.value.total ?? 0, color: '#409eff' },
  { key: 'publishing', label: '发布中', value: stats.value.publishing ?? 0, color: '#e6a23c' },
  { key: 'published', label: '已发布', value: stats.value.published ?? 0, color: '#67c23a' },
  { key: 'failed', label: '失败', value: stats.value.failed ?? 0, color: '#f56c6c' },
  {
    key: 'success_rate',
    label: '成功率',
    value: `${stats.value.success_rate ?? 0}%`,
    color: '#409eff',
  },
])
async function loadStats() {
  try {
    stats.value = await apiGetPublishStats()
  } catch {
    stats.value = {}
  }
}

// ---------- 列表 ----------
const loading = ref(false)
const list = ref<PublishTask[]>([])
const total = ref(0)
const query = reactive<{
  page: number
  page_size: number
  status?: string
  mp_account_id?: number
  keyword: string
}>({ page: 1, page_size: 10, status: undefined, mp_account_id: undefined, keyword: '' })

async function loadList() {
  loading.value = true
  try {
    const data = await apiListPublishTasks({
      page: query.page,
      page_size: query.page_size,
      status: query.status || undefined,
      mp_account_id: query.mp_account_id,
      keyword: query.keyword || undefined,
    })
    list.value = data.items
    total.value = data.total
  } finally {
    loading.value = false
  }
}
function refreshAll() {
  loadStats()
  loadList()
}
function onSearch() {
  query.page = 1
  loadList()
}
function onReset() {
  query.keyword = ''
  query.status = undefined
  query.mp_account_id = undefined
  query.page = 1
  refreshAll()
}

// ---------- 单任务操作 ----------
const busyId = ref<number | null>(null)

async function onCancel(row: PublishTask) {
  try {
    await ElMessageBox.confirm(`确定取消任务 #${row.id}?`, '取消发布', {
      type: 'warning',
      confirmButtonText: '取消任务',
      cancelButtonText: '返回',
    })
  } catch {
    return
  }
  busyId.value = row.id
  try {
    await apiCancelPublishTask(row.id)
    ElMessage.success('已取消')
    refreshAll()
  } finally {
    busyId.value = null
  }
}

async function onRetry(row: PublishTask) {
  busyId.value = row.id
  try {
    await apiRetryPublishTask(row.id)
    ElMessage.success('已重新提交')
    refreshAll()
  } finally {
    busyId.value = null
  }
}

// 一键下架已发布文章
async function onTakedown(row: PublishTask) {
  try {
    await ElMessageBox.confirm(`确定下架任务 #${row.id} 已发布的文章?`, '下架文章', {
      type: 'warning',
      confirmButtonText: '确认下架',
      cancelButtonText: '返回',
    })
  } catch {
    return
  }
  busyId.value = row.id
  try {
    await apiTakedownPublishTask(row.id)
    ElMessage.success('已下架')
    refreshAll()
  } finally {
    busyId.value = null
  }
}

// ---------- 日志抽屉 ----------
const logVisible = ref(false)
const logLoading = ref(false)
const logs = ref<PublishLog[]>([])
const logTask = ref<PublishTask | null>(null)
async function openLogs(row: PublishTask) {
  logTask.value = row
  logVisible.value = true
  logLoading.value = true
  try {
    logs.value = await apiGetPublishTaskLogs(row.id)
  } finally {
    logLoading.value = false
  }
}
// errcode 为 0 或空视为成功, 非 0 视为失败
function logTagType(errcode?: number): 'info' | 'danger' | 'success' {
  if (errcode == null || errcode === 0) return 'success'
  return 'danger'
}

onMounted(refreshAll)
</script>

<template>
  <div class="page-container">
    <!-- 统计卡片 -->
    <el-row :gutter="16" class="stat-row">
      <el-col v-for="c in statCards" :key="c.key" :xs="12" :sm="6">
        <div class="stat-card">
          <div class="stat-value" :style="{ color: c.color }">{{ c.value }}</div>
          <div class="stat-label">{{ c.label }}</div>
        </div>
      </el-col>
    </el-row>

    <div class="page-toolbar">
      <div class="left">
        <el-input
          v-model="query.keyword"
          placeholder="搜索标题"
          clearable
          style="width: 180px"
          @keyup.enter="onSearch"
          @clear="onSearch"
        />
        <el-select
          v-model="query.mp_account_id"
          placeholder="公众号"
          clearable
          filterable
          style="width: 170px"
          @change="onSearch"
        >
          <el-option v-for="mp in mpOptions" :key="mp.id" :label="mp.mp_name" :value="mp.id" />
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
        <el-button @click="refreshAll">
          <el-icon><Refresh /></el-icon>刷新
        </el-button>
      </div>
    </div>

    <el-table v-loading="loading" :data="list" border stripe>
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column prop="title" label="标题" min-width="200" show-overflow-tooltip>
        <template #default="{ row }">
          {{ row.title || (row.draft_group_id ? '多图文组 #' + row.draft_group_id : '#' + row.id) }}
        </template>
      </el-table-column>
      <el-table-column label="公众号" min-width="140">
        <template #default="{ row }">{{ row.mp_name || row.mp_account_id || '-' }}</template>
      </el-table-column>
      <el-table-column label="状态" width="100" align="center">
        <template #default="{ row }">
          <el-tag :type="statusMeta(row.status).type" size="small" effect="dark">
            {{ statusMeta(row.status).label }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="scheduled_at" label="计划时间" min-width="160">
        <template #default="{ row }">{{ row.scheduled_at || '立即' }}</template>
      </el-table-column>
      <el-table-column prop="created_at" label="创建时间" min-width="160" />
      <el-table-column label="操作" width="330" fixed="right">
        <template #default="{ row }">
          <el-button link type="info" @click="openLogs(row as PublishTask)">日志</el-button>
          <el-button
            v-if="canOperate && (row as PublishTask).status === 'FAILED'"
            link
            type="warning"
            :loading="busyId === (row as PublishTask).id"
            @click="onRetry(row as PublishTask)"
          >
            重试
          </el-button>
          <el-button
            v-if="canOperate && (row as PublishTask).status === 'SCHEDULED'"
            link
            type="danger"
            :loading="busyId === (row as PublishTask).id"
            @click="onCancel(row as PublishTask)"
          >
            取消
          </el-button>
          <el-button
            v-if="canManage && (row as PublishTask).status === 'PUBLISHED'"
            link
            type="danger"
            :loading="busyId === (row as PublishTask).id"
            @click="onTakedown(row as PublishTask)"
          >
            下架
          </el-button>
          <el-link
            v-if="(row as PublishTask).published_url"
            :href="(row as PublishTask).published_url"
            target="_blank"
            type="success"
            class="pub-link"
          >
            查看
          </el-link>
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

    <!-- 日志抽屉 -->
    <el-drawer v-model="logVisible" title="发布日志" size="520px">
      <div v-if="logTask" class="log-head">
        <span>任务 #{{ logTask.id }}</span>
        <el-tag :type="statusMeta(logTask.status).type" size="small">
          {{ statusMeta(logTask.status).label }}
        </el-tag>
      </div>
      <el-alert
        v-if="logTask?.last_errmsg"
        type="error"
        :closable="false"
        :title="logTask.last_errmsg"
        class="log-err"
        show-icon
      />
      <el-timeline v-loading="logLoading" class="log-timeline">
        <el-timeline-item
          v-for="lg in logs"
          :key="lg.id"
          :timestamp="lg.created_at"
          placement="top"
          :type="logTagType(lg.errcode)"
        >
          <el-tag :type="logTagType(lg.errcode)" size="small" class="log-level">
            {{ lg.phase || '-' }}
          </el-tag>
          <span class="log-msg">
            {{ lg.errcode ? `errcode ${lg.errcode}: ${lg.errmsg || ''}` : lg.errmsg || '成功' }}
          </span>
        </el-timeline-item>
      </el-timeline>
      <el-empty v-if="!logLoading && !logs.length" description="暂无日志" />
    </el-drawer>
  </div>
</template>

<style scoped>
.stat-row {
  margin-bottom: 16px;
}
.stat-card {
  background: #fff;
  border-radius: 8px;
  padding: 18px 20px;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.04);
}
.stat-value {
  font-size: 28px;
  font-weight: 700;
  line-height: 1.2;
}
.stat-label {
  margin-top: 4px;
  font-size: 13px;
  color: #909399;
}
.pager {
  margin-top: 16px;
  display: flex;
  justify-content: flex-end;
}
.pub-link {
  margin-left: 8px;
  font-size: 13px;
  vertical-align: middle;
}
.log-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
  font-weight: 600;
}
.log-err {
  margin-bottom: 12px;
}
.log-timeline {
  margin-top: 8px;
}
.log-level {
  margin-right: 8px;
  text-transform: uppercase;
}
.log-msg {
  color: #303133;
  word-break: break-all;
}
</style>
