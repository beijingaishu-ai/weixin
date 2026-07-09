<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { apiSchedulerDashboard, apiSchedulerTick } from '@/api/modules'
import { useAuthStore } from '@/stores/auth'
import type { SchedulerDashboard, SchedulerTickResult } from '@/api/types'

const auth = useAuthStore()

const visibleCount = computed(() => auth.visibleMp.length)
const canTick = computed(() => auth.hasPerm('system:config:manage'))

// ---------- 运营看板 ----------
const dash = ref<SchedulerDashboard>({})
const dashLoading = ref(false)

async function loadDashboard() {
  dashLoading.value = true
  try {
    dash.value = await apiSchedulerDashboard()
  } catch {
    dash.value = {}
  } finally {
    dashLoading.value = false
  }
}

// 顶部概览卡片
const overviewCards = computed(() => [
  { key: 'mp', label: '公众号数', value: dash.value.mp_total ?? 0, color: '#409eff' },
  {
    key: 'sources',
    label: '采集源数',
    value: dash.value.sources_total ?? 0,
    color: '#67c23a',
    extra: dash.value.sources_circuit ? `熔断 ${dash.value.sources_circuit}` : '',
  },
  {
    key: 'rate',
    label: '发布成功率',
    value: `${dash.value.publish_success_rate ?? 0}%`,
    color: '#e6a23c',
  },
  {
    key: 'pending',
    label: '待审核',
    value: dash.value.pending_review ?? 0,
    color: '#f56c6c',
  },
])

// 引擎状态计数 (采集 / 内容 / 发布)
function toEntries(m?: Record<string, number>): Array<{ status: string; count: number }> {
  if (!m) return []
  return Object.entries(m).map(([status, count]) => ({ status, count: Number(count) || 0 }))
}
const collectEntries = computed(() => toEntries(dash.value.collect_by_status))
const contentEntries = computed(() => toEntries(dash.value.content_by_status))
const taskEntries = computed(() => toEntries(dash.value.task_by_status))

// 状态标签配色 (后端真实状态值)
const STATUS_TYPE: Record<string, 'info' | 'warning' | 'success' | 'danger' | 'primary'> = {
  // 采集文章
  COLLECTED: 'info',
  MAPPED: 'warning',
  TRANSFORMED: 'warning',
  UNMATCHED: 'danger',
  // 内容图文
  PENDING_REVIEW: 'primary',
  APPROVED: 'success',
  REJECTED: 'danger',
  DRAFT_CREATED: 'info',
  // 发布任务
  SCHEDULED: 'info',
  PUBLISHING: 'warning',
  PUBLISHED: 'success',
  FAILED: 'danger',
}
function statusType(s: string) {
  return STATUS_TYPE[s] || 'info'
}

// ---------- 手动执行流水线 ----------
const ticking = ref(false)
const TICK_FIELDS: Array<{ key: keyof SchedulerTickResult; label: string }> = [
  { key: 'sources_due', label: '到期源' },
  { key: 'collected', label: '采集' },
  { key: 'mapped_transformed', label: '映射转换' },
  { key: 'auto_submitted', label: '自动提审' },
  { key: 'auto_created_tasks', label: '建任务' },
  { key: 'published', label: '发表' },
  { key: 'failed', label: '失败' },
  { key: 'retried', label: '重试' },
  { key: 'dead_letter_alerts', label: '死信告警' },
]
async function onTick() {
  ticking.value = true
  try {
    const r = await apiSchedulerTick()
    const html = TICK_FIELDS.map(
      (f) => `<div class="tick-line"><span>${f.label}</span><b>${r[f.key] ?? 0}</b></div>`,
    ).join('')
    ElMessageBox.alert(`<div class="tick-box">${html}</div>`, '流水线执行结果', {
      dangerouslyUseHTMLString: true,
      confirmButtonText: '知道了',
    }).catch(() => {})
    ElMessage.success('流水线已执行一次')
    loadDashboard()
  } finally {
    ticking.value = false
  }
}

onMounted(loadDashboard)
</script>

<template>
  <div class="page-container">
    <el-card shadow="never" class="welcome-card">
      <div class="welcome">
        <el-avatar :size="56" class="welcome-avatar">
          {{ (auth.realName || auth.username || '?').slice(0, 1) }}
        </el-avatar>
        <div class="welcome-text">
          <h2>你好, {{ auth.realName || auth.username }}</h2>
          <p>
            当前角色:
            <el-tag size="small">{{ auth.role || '-' }}</el-tag>
            <template v-if="auth.roles.length > 1">
              <el-tag
                v-for="r in auth.roles"
                :key="r"
                size="small"
                type="info"
                class="role-chip"
              >
                {{ r }}
              </el-tag>
            </template>
          </p>
        </div>
        <div class="welcome-actions">
          <el-button
            v-if="canTick"
            type="primary"
            :loading="ticking"
            @click="onTick"
          >
            <el-icon><VideoPlay /></el-icon>手动执行流水线一次
          </el-button>
        </div>
      </div>
    </el-card>

    <!-- 概览卡片 -->
    <el-row v-loading="dashLoading" :gutter="16" class="stat-row">
      <el-col v-for="c in overviewCards" :key="c.key" :xs="12" :sm="6">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-value" :style="{ color: c.color }">{{ c.value }}</div>
          <div class="stat-label">
            {{ c.label }}
            <el-tag v-if="c.extra" size="small" type="danger" class="stat-extra">{{ c.extra }}</el-tag>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 各引擎状态计数 -->
    <el-row :gutter="16" class="engine-row">
      <el-col :xs="24" :md="8">
        <el-card shadow="never" class="engine-card">
          <template #header><span>采集引擎</span></template>
          <div v-if="collectEntries.length" class="engine-stats">
            <el-statistic
              v-for="e in collectEntries"
              :key="e.status"
              :value="e.count"
            >
              <template #title>
                <el-tag :type="statusType(e.status)" size="small">{{ e.status }}</el-tag>
              </template>
            </el-statistic>
          </div>
          <el-empty v-else :image-size="60" description="暂无数据" />
        </el-card>
      </el-col>
      <el-col :xs="24" :md="8">
        <el-card shadow="never" class="engine-card">
          <template #header><span>内容引擎</span></template>
          <div v-if="contentEntries.length" class="engine-stats">
            <el-statistic
              v-for="e in contentEntries"
              :key="e.status"
              :value="e.count"
            >
              <template #title>
                <el-tag :type="statusType(e.status)" size="small">{{ e.status }}</el-tag>
              </template>
            </el-statistic>
          </div>
          <el-empty v-else :image-size="60" description="暂无数据" />
        </el-card>
      </el-col>
      <el-col :xs="24" :md="8">
        <el-card shadow="never" class="engine-card">
          <template #header><span>发布引擎</span></template>
          <div v-if="taskEntries.length" class="engine-stats">
            <el-statistic
              v-for="e in taskEntries"
              :key="e.status"
              :value="e.count"
            >
              <template #title>
                <el-tag :type="statusType(e.status)" size="small">{{ e.status }}</el-tag>
              </template>
            </el-statistic>
          </div>
          <el-empty v-else :image-size="60" description="暂无数据" />
        </el-card>
      </el-col>
    </el-row>

    <el-card v-if="visibleCount" shadow="never" class="mp-list-card">
      <template #header>
        <span>我可见的公众号</span>
      </template>
      <el-table :data="auth.visibleMp" size="small" border stripe>
        <el-table-column prop="id" label="ID" width="80" />
        <el-table-column prop="mp_name" label="公众号名称" min-width="200" />
        <el-table-column prop="perm_level" label="权限级别" width="140">
          <template #default="{ row }">
            <el-tag size="small">{{ row.perm_level }}</el-tag>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<style scoped>
.welcome-card {
  margin-bottom: 16px;
}
.welcome {
  display: flex;
  align-items: center;
  gap: 16px;
}
.welcome-avatar {
  background-color: #409eff;
  color: #fff;
  font-size: 22px;
}
.welcome-text h2 {
  margin: 0 0 6px;
  font-size: 20px;
}
.welcome-text p {
  margin: 0;
  color: #606266;
}
.welcome-actions {
  margin-left: auto;
}
.role-chip {
  margin-left: 6px;
}

.stat-row {
  margin-bottom: 16px;
}
.stat-card {
  margin-bottom: 16px;
}
.stat-value {
  font-size: 28px;
  font-weight: 700;
  line-height: 1.1;
}
.stat-label {
  color: #909399;
  font-size: 13px;
  margin-top: 4px;
}
.stat-extra {
  margin-left: 6px;
}

.engine-row {
  margin-bottom: 16px;
}
.engine-card {
  margin-bottom: 16px;
}
.engine-stats {
  display: flex;
  flex-wrap: wrap;
  gap: 18px 24px;
}
</style>
