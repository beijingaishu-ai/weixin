<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  apiDeleteCollectArticle,
  apiGetCollectArticle,
  apiGetCollectArticleDedupInfo,
  apiListCollectArticles,
  apiListCollectSources,
  apiMappingRunPending,
} from '@/api/modules'
import { useAuthStore } from '@/stores/auth'
import type { CollectArticle, CollectSource } from '@/api/types'

const auth = useAuthStore()
const canManage = auth.hasPerm('collect:source:manage')
const canRunMapping = auth.hasPerm('mapping:rule:manage')

const STATUS_META: Record<string, { label: string; type: 'info' | 'primary' | 'success' | 'warning' | 'danger' }> = {
  COLLECTED: { label: '待映射', type: 'info' },
  MAPPED: { label: '已命中', type: 'primary' },
  TRANSFORMED: { label: '已转换', type: 'success' },
  UNMATCHED: { label: '未匹配', type: 'warning' },
}
const STATUS_OPTIONS = Object.entries(STATUS_META).map(([value, m]) => ({ value, label: m.label }))

const loading = ref(false)
const list = ref<CollectArticle[]>([])
const total = ref(0)
const sources = ref<CollectSource[]>([])
const query = reactive({ page: 1, page_size: 10, keyword: '', status: '', source_id: undefined as number | undefined })

function sourceName(id?: number): string {
  return sources.value.find((s) => s.id === id)?.source_name || (id != null ? `#${id}` : '-')
}

async function loadSources() {
  try {
    const data = await apiListCollectSources({ page: 1, page_size: 100 })
    sources.value = data.items
  } catch {
    /* ignore */
  }
}

async function loadList() {
  loading.value = true
  try {
    const data = await apiListCollectArticles({
      page: query.page,
      page_size: query.page_size,
      keyword: query.keyword || undefined,
      status: query.status || undefined,
      source_id: query.source_id,
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
  query.status = ''
  query.source_id = undefined
  query.page = 1
  loadList()
}

// ---------- 处理待映射 ----------
const running = ref(false)
async function onRunPending() {
  running.value = true
  try {
    const r = (await apiMappingRunPending()) as Record<string, number>
    ElMessage.success(
      `处理 ${r.processed ?? 0} 篇:转换 ${r.transformed ?? 0}、未匹配 ${r.unmatched ?? 0}、产出图文 ${r.produced_content ?? 0}`,
    )
    loadList()
  } finally {
    running.value = false
  }
}

// ---------- 详情抽屉 ----------
const detailVisible = ref(false)
const detail = ref<CollectArticle | null>(null)
const dedup = ref<Record<string, unknown> | null>(null)
async function openDetail(row: CollectArticle) {
  detailVisible.value = true
  detail.value = null
  dedup.value = null
  detail.value = await apiGetCollectArticle(row.id)
  try {
    dedup.value = (await apiGetCollectArticleDedupInfo(row.id)) as Record<string, unknown>
  } catch {
    /* ignore */
  }
}

async function onDelete(row: CollectArticle) {
  await ElMessageBox.confirm(`确认删除采集文章「${row.title}」?`, '提示', { type: 'warning' })
  await apiDeleteCollectArticle(row.id)
  ElMessage.success('已删除')
  loadList()
}

onMounted(() => {
  loadSources()
  loadList()
})
</script>

<template>
  <div class="page-container">
    <div class="page-toolbar">
      <div class="left">
        <el-select v-model="query.source_id" placeholder="全部采集源" clearable style="width: 160px" @change="onSearch">
          <el-option v-for="s in sources" :key="s.id" :label="s.source_name" :value="s.id" />
        </el-select>
        <el-select v-model="query.status" placeholder="全部状态" clearable style="width: 130px" @change="onSearch">
          <el-option v-for="o in STATUS_OPTIONS" :key="o.value" :label="o.label" :value="o.value" />
        </el-select>
        <el-input v-model="query.keyword" placeholder="搜索标题" clearable style="width: 200px" @keyup.enter="onSearch" @clear="onReset" />
        <el-button type="primary" @click="onSearch"><el-icon><Search /></el-icon>搜索</el-button>
        <el-button @click="onReset">重置</el-button>
      </div>
      <div class="right">
        <el-button v-if="canRunMapping" type="success" :loading="running" @click="onRunPending">
          <el-icon><MagicStick /></el-icon>处理待映射
        </el-button>
      </div>
    </div>

    <el-table v-loading="loading" :data="list" border stripe>
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column prop="title" label="标题" min-width="220" show-overflow-tooltip />
      <el-table-column label="来源" min-width="120">
        <template #default="{ row }">{{ (row as CollectArticle).source_name || sourceName((row as CollectArticle).source_id) }}</template>
      </el-table-column>
      <el-table-column label="原创标" width="80" align="center">
        <template #default="{ row }">
          <el-tag v-if="(row as CollectArticle).is_original_marked" type="danger" size="small">原创</el-tag>
          <span v-else class="muted">-</span>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="110">
        <template #default="{ row }">
          <el-tag :type="STATUS_META[(row as CollectArticle).status]?.type || 'info'" size="small">
            {{ STATUS_META[(row as CollectArticle).status]?.label || (row as CollectArticle).status }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="备注" min-width="160">
        <template #default="{ row }">
          <span v-if="(row as CollectArticle).dedup_of" class="muted">重复(→#{{ (row as CollectArticle).dedup_of }})</span>
          <span v-else-if="(row as CollectArticle).unmatched_reason" class="warn-text">{{ (row as CollectArticle).unmatched_reason }}</span>
          <span v-else class="muted">-</span>
        </template>
      </el-table-column>
      <el-table-column prop="collected_at" label="采集时间" min-width="160" />
      <el-table-column label="操作" width="150" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="openDetail(row as CollectArticle)">详情</el-button>
          <el-button
            v-if="canManage && ['COLLECTED', 'UNMATCHED'].includes((row as CollectArticle).status)"
            link
            type="danger"
            @click="onDelete(row as CollectArticle)"
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

    <el-drawer v-model="detailVisible" title="采集文章详情" size="60%">
      <div v-if="detail">
        <h3 class="art-title">{{ detail.title }}</h3>
        <p class="muted">
          作者: {{ detail.author || '-' }} ·
          <a v-if="detail.url" :href="detail.url" target="_blank">原文链接</a>
        </p>
        <el-descriptions v-if="dedup" :column="2" border size="small" class="mb">
          <el-descriptions-item label="状态">{{ detail.status }}</el-descriptions-item>
          <el-descriptions-item label="SimHash">{{ dedup.simhash }}</el-descriptions-item>
          <el-descriptions-item label="去重命中">{{ dedup.dedup_of ?? '无' }}</el-descriptions-item>
          <el-descriptions-item label="Hamming">{{ dedup.hamming_to_dup ?? '-' }}</el-descriptions-item>
        </el-descriptions>
        <el-tabs>
          <el-tab-pane label="清洗后正文">
            <div class="html-preview" v-html="(detail as Record<string, unknown>).clean_html as string" />
          </el-tab-pane>
          <el-tab-pane label="原始 HTML">
            <pre class="raw-html">{{ (detail as Record<string, unknown>).raw_html }}</pre>
          </el-tab-pane>
        </el-tabs>
      </div>
      <el-empty v-else description="加载中..." />
    </el-drawer>
  </div>
</template>

<style scoped>
.pager { margin-top: 16px; display: flex; justify-content: flex-end; }
.muted { color: #909399; }
.warn-text { color: #e6a23c; }
.art-title { margin: 0 0 8px; }
.mb { margin: 12px 0; }
.html-preview { border: 1px solid #ebeef5; border-radius: 6px; padding: 16px; max-height: 50vh; overflow: auto; }
.raw-html { background: #f5f7fa; padding: 12px; border-radius: 6px; max-height: 50vh; overflow: auto; white-space: pre-wrap; word-break: break-all; font-size: 12px; }
</style>
