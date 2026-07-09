<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { apiAuditArticle, apiListArticles } from '@/api/modules'
import { useAuthStore } from '@/stores/auth'
import type { Article } from '@/api/types'

const auth = useAuthStore()
const canAudit = computed(
  () => auth.hasPerm('content:article:audit') || auth.hasPerm('user:manage'),
)

// ---------- 列表 ----------
const loading = ref(false)
const list = ref<Article[]>([])
const total = ref(0)
const query = reactive<{ page: number; page_size: number }>({ page: 1, page_size: 10 })

async function loadList() {
  loading.value = true
  try {
    const data = await apiListArticles({
      status: 'PENDING_REVIEW',
      page: query.page,
      page_size: query.page_size,
    })
    list.value = data.items
    total.value = data.total
  } finally {
    loading.value = false
  }
}

// ---------- 审核 ----------
const busyId = ref<number | null>(null)

async function onPass(row: Article) {
  busyId.value = row.id
  try {
    await apiAuditArticle(row.id, 'pass')
    ElMessage.success('已通过')
    reload()
  } finally {
    busyId.value = null
  }
}

// 驳回弹框(必填意见)
const rejectVisible = ref(false)
const rejectRow = ref<Article | null>(null)
const rejectOpinion = ref('')
const rejectSaving = ref(false)

function openReject(row: Article) {
  rejectRow.value = row
  rejectOpinion.value = ''
  rejectVisible.value = true
}
async function submitReject() {
  if (!rejectRow.value) return
  if (!rejectOpinion.value.trim()) {
    ElMessage.warning('驳回时请填写审核意见')
    return
  }
  rejectSaving.value = true
  try {
    await apiAuditArticle(rejectRow.value.id, 'reject', rejectOpinion.value.trim())
    ElMessage.success('已驳回')
    rejectVisible.value = false
    reload()
  } finally {
    rejectSaving.value = false
  }
}

// 审核后若当前页可能空掉, 回退一页
function reload() {
  if (list.value.length <= 1 && query.page > 1) query.page -= 1
  loadList()
}

onMounted(loadList)
</script>

<template>
  <div class="page-container">
    <div class="page-toolbar">
      <div class="left">
        <span class="queue-title">审核队列</span>
        <el-tag type="primary" effect="dark" class="queue-count">待审核 {{ total }}</el-tag>
      </div>
      <div class="right">
        <el-button @click="loadList">
          <el-icon><Refresh /></el-icon>刷新
        </el-button>
      </div>
    </div>

    <el-table v-loading="loading" :data="list" border stripe>
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column prop="title" label="标题" min-width="220" show-overflow-tooltip />
      <el-table-column label="公众号" min-width="140">
        <template #default="{ row }">{{ row.mp_name || row.mp_account_id || '-' }}</template>
      </el-table-column>
      <el-table-column label="来源" min-width="140">
        <template #default="{ row }">
          {{ row.source_name || row.author || '-' }}
        </template>
      </el-table-column>
      <el-table-column prop="created_at" label="创建时间" min-width="160">
        <template #default="{ row }">{{ row.created_at || '-' }}</template>
      </el-table-column>
      <el-table-column label="操作" width="180" fixed="right" align="center">
        <template #default="{ row }">
          <el-button
            v-if="canAudit"
            link
            type="success"
            :loading="busyId === (row as Article).id"
            @click="onPass(row as Article)"
          >
            通过
          </el-button>
          <el-button
            v-if="canAudit"
            link
            type="danger"
            @click="openReject(row as Article)"
          >
            驳回
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
        @size-change="loadList"
      />
    </div>

    <el-empty v-if="!loading && !list.length" description="暂无待审核图文" />

    <!-- 驳回对话框 -->
    <el-dialog v-model="rejectVisible" title="驳回图文" width="520px">
      <p class="dialog-sub">标题: <b>{{ rejectRow?.title }}</b></p>
      <el-form label-width="80px">
        <el-form-item label="驳回理由" required>
          <el-input
            v-model="rejectOpinion"
            type="textarea"
            :rows="3"
            placeholder="请填写驳回理由 (必填)"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="rejectVisible = false">取消</el-button>
        <el-button type="danger" :loading="rejectSaving" @click="submitReject">确认驳回</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.queue-title {
  font-size: 16px;
  font-weight: 600;
  color: #303133;
  margin-right: 12px;
}
.queue-count {
  vertical-align: middle;
}
.pager {
  margin-top: 16px;
  display: flex;
  justify-content: flex-end;
}
.dialog-sub {
  margin: 0 0 16px;
  color: #606266;
}
</style>
