<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  apiAuditArticle,
  apiCreatePublishTask,
  apiListArticles,
  apiSubmitArticle,
} from '@/api/modules'
import { useAuthStore } from '@/stores/auth'
import type { Article, ArticleStatus } from '@/api/types'

const auth = useAuthStore()
const router = useRouter()

const canEdit = computed(
  () => auth.hasPerm('content:article:edit') || auth.hasPerm('user:manage'),
)
const canAudit = computed(
  () => auth.hasPerm('content:article:audit') || auth.hasPerm('user:manage'),
)
const canPublish = computed(
  () => auth.hasPerm('publish:task:create') || auth.hasPerm('publish:task:view') || auth.hasPerm('user:manage'),
)

const mpOptions = computed(() => auth.visibleMp)

const STATUS_OPTIONS: Array<{ value: ArticleStatus; label: string }> = [
  { value: 'TRANSFORMED', label: '待提审' },
  { value: 'PENDING_REVIEW', label: '待审核' },
  { value: 'APPROVED', label: '已通过' },
  { value: 'REJECTED', label: '已驳回' },
  { value: 'DRAFT_CREATED', label: '已建草稿' },
]

const STATUS_META: Record<
  string,
  { label: string; type: 'info' | 'warning' | 'success' | 'danger' | 'primary' }
> = {
  TRANSFORMED: { label: '待提审', type: 'warning' },
  PENDING_REVIEW: { label: '待审核', type: 'primary' },
  APPROVED: { label: '已通过', type: 'success' },
  REJECTED: { label: '已驳回', type: 'danger' },
  DRAFT_CREATED: { label: '已建草稿', type: 'info' },
}
function statusMeta(s: string) {
  return STATUS_META[s] || { label: s || '-', type: 'info' as const }
}

const loading = ref(false)
const list = ref<Article[]>([])
const total = ref(0)
const query = reactive<{
  page: number
  page_size: number
  keyword: string
  status?: ArticleStatus
  mp_account_id?: number
}>({
  page: 1,
  page_size: 10,
  keyword: '',
  status: undefined,
  mp_account_id: undefined,
})

async function loadList() {
  loading.value = true
  try {
    const data = await apiListArticles({
      page: query.page,
      page_size: query.page_size,
      keyword: query.keyword || undefined,
      status: query.status || undefined,
      mp_account_id: query.mp_account_id,
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
  query.status = undefined
  query.mp_account_id = undefined
  query.page = 1
  loadList()
}

function goCreate() {
  router.push({ name: 'article-new' })
}
function goEdit(row: Article) {
  router.push({ name: 'article-edit', params: { id: row.id } })
}

// ---------- 提审 ----------
const busyId = ref<number | null>(null)
async function onSubmit(row: Article) {
  try {
    await ElMessageBox.confirm(`确定提交「${row.title}」进入审核?`, '提交审核', {
      type: 'warning',
      confirmButtonText: '提交',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  busyId.value = row.id
  try {
    await apiSubmitArticle(row.id)
    ElMessage.success('已提交审核')
    loadList()
  } finally {
    busyId.value = null
  }
}

// ---------- 审核 ----------
const auditVisible = ref(false)
const auditRow = ref<Article | null>(null)
const auditResult = ref<'pass' | 'reject'>('pass')
const auditOpinion = ref('')
const auditSaving = ref(false)

function openAudit(row: Article) {
  auditRow.value = row
  auditResult.value = 'pass'
  auditOpinion.value = ''
  auditVisible.value = true
}
async function submitAudit() {
  if (!auditRow.value) return
  if (auditResult.value === 'reject' && !auditOpinion.value.trim()) {
    ElMessage.warning('驳回时请填写审核意见')
    return
  }
  auditSaving.value = true
  try {
    await apiAuditArticle(auditRow.value.id, auditResult.value, auditOpinion.value || undefined)
    ElMessage.success(auditResult.value === 'pass' ? '已通过' : '已驳回')
    auditVisible.value = false
    loadList()
  } finally {
    auditSaving.value = false
  }
}

// ---------- 去发布 ----------
const publishVisible = ref(false)
const publishRow = ref<Article | null>(null)
const publishForm = reactive<{ mp_account_id?: number; scheduled_at: string }>({
  mp_account_id: undefined,
  scheduled_at: '',
})
const publishSaving = ref(false)

function openPublish(row: Article) {
  publishRow.value = row
  publishForm.mp_account_id = row.mp_account_id
  publishForm.scheduled_at = ''
  publishVisible.value = true
}
async function submitPublish() {
  if (!publishRow.value) return
  if (!publishForm.mp_account_id) {
    ElMessage.warning('请选择发布的公众号')
    return
  }
  publishSaving.value = true
  try {
    await apiCreatePublishTask({
      content_article_id: publishRow.value.id,
      mp_account_id: publishForm.mp_account_id,
      scheduled_at: publishForm.scheduled_at || undefined,
    })
    ElMessage.success('已创建发布任务')
    publishVisible.value = false
    ElMessageBox.confirm('发布任务已创建, 是否前往发布任务列表查看进度?', '提示', {
      confirmButtonText: '前往查看',
      cancelButtonText: '留在此页',
      type: 'success',
    })
      .then(() => router.push({ name: 'publish-tasks' }))
      .catch(() => {})
  } finally {
    publishSaving.value = false
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
          placeholder="搜索标题"
          clearable
          style="width: 200px"
          @keyup.enter="onSearch"
          @clear="onSearch"
        />
        <el-select
          v-model="query.mp_account_id"
          placeholder="公众号"
          clearable
          filterable
          style="width: 180px"
          @change="onSearch"
        >
          <el-option v-for="mp in mpOptions" :key="mp.id" :label="mp.mp_name" :value="mp.id" />
        </el-select>
        <el-select
          v-model="query.status"
          placeholder="状态"
          clearable
          style="width: 140px"
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
        <el-button v-if="canEdit" type="primary" @click="goCreate">
          <el-icon><Plus /></el-icon>新建图文
        </el-button>
      </div>
    </div>

    <el-table v-loading="loading" :data="list" border stripe>
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column label="封面" width="90">
        <template #default="{ row }">
          <el-image
            v-if="row.cover_url"
            :src="row.cover_url"
            fit="cover"
            style="width: 56px; height: 40px; border-radius: 4px"
          />
          <span v-else class="muted">-</span>
        </template>
      </el-table-column>
      <el-table-column prop="title" label="标题" min-width="200" show-overflow-tooltip />
      <el-table-column label="公众号" min-width="140">
        <template #default="{ row }">
          {{ row.mp_name || row.mp_account_id || '-' }}
        </template>
      </el-table-column>
      <el-table-column prop="author" label="作者" width="110">
        <template #default="{ row }">{{ row.author || '-' }}</template>
      </el-table-column>
      <el-table-column label="状态" width="100" align="center">
        <template #default="{ row }">
          <el-tag :type="statusMeta(row.status).type" size="small">
            {{ statusMeta(row.status).label }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="updated_at" label="更新时间" min-width="160" />
      <el-table-column label="操作" width="300" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="goEdit(row as Article)">
            {{ (row as Article).status === 'TRANSFORMED' || (row as Article).status === 'REJECTED' ? '编辑' : '查看' }}
          </el-button>
          <el-button
            v-if="canEdit && ((row as Article).status === 'TRANSFORMED' || (row as Article).status === 'REJECTED')"
            link
            type="warning"
            :loading="busyId === (row as Article).id"
            @click="onSubmit(row as Article)"
          >
            提审
          </el-button>
          <el-button
            v-if="canAudit && (row as Article).status === 'PENDING_REVIEW'"
            link
            type="success"
            @click="openAudit(row as Article)"
          >
            审核
          </el-button>
          <el-button
            v-if="canPublish && (row as Article).status === 'APPROVED'"
            link
            type="primary"
            @click="openPublish(row as Article)"
          >
            去发布
          </el-button>
          <el-link
            v-if="(row as Article).published_url"
            :href="(row as Article).published_url as string"
            target="_blank"
            type="primary"
            class="pub-link"
          >
            已发布链接
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

    <!-- 审核对话框 -->
    <el-dialog v-model="auditVisible" title="审核图文" width="520px">
      <p class="dialog-sub">标题: <b>{{ auditRow?.title }}</b></p>
      <el-form label-width="80px">
        <el-form-item label="审核结果">
          <el-radio-group v-model="auditResult">
            <el-radio value="pass">通过</el-radio>
            <el-radio value="reject">驳回</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item :label="auditResult === 'reject' ? '驳回理由' : '审核意见'">
          <el-input
            v-model="auditOpinion"
            type="textarea"
            :rows="3"
            :placeholder="auditResult === 'reject' ? '请填写驳回理由 (必填)' : '审核意见 (可选)'"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="auditVisible = false">取消</el-button>
        <el-button
          :type="auditResult === 'reject' ? 'danger' : 'success'"
          :loading="auditSaving"
          @click="submitAudit"
        >
          {{ auditResult === 'reject' ? '确认驳回' : '确认通过' }}
        </el-button>
      </template>
    </el-dialog>

    <!-- 去发布对话框 -->
    <el-dialog v-model="publishVisible" title="创建发布任务" width="520px">
      <p class="dialog-sub">图文: <b>{{ publishRow?.title }}</b></p>
      <el-form label-width="90px">
        <el-form-item label="公众号" required>
          <el-select
            v-model="publishForm.mp_account_id"
            placeholder="选择发布的公众号"
            style="width: 100%"
            filterable
          >
            <el-option v-for="mp in mpOptions" :key="mp.id" :label="mp.mp_name" :value="mp.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="定时发布">
          <el-date-picker
            v-model="publishForm.scheduled_at"
            type="datetime"
            placeholder="留空即立即发布"
            value-format="YYYY-MM-DD HH:mm:ss"
            style="width: 100%"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="publishVisible = false">取消</el-button>
        <el-button type="primary" :loading="publishSaving" @click="submitPublish">
          创建任务
        </el-button>
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
.pub-link {
  margin-left: 8px;
  font-size: 13px;
  vertical-align: middle;
}
</style>
