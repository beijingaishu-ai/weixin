<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import {
  apiCreateArticle,
  apiGetArticle,
  apiListArticleVersions,
  apiListStyleTemplates,
  apiRollbackArticle,
  apiSubmitArticle,
  apiUpdateArticle,
  type ArticlePayload,
} from '@/api/modules'
import { useAuthStore } from '@/stores/auth'
import type { ArticleStatus, ArticleVersion, Material, StyleTemplate } from '@/api/types'
import RichEditor from '@/components/RichEditor.vue'
import MaterialPicker from '@/components/MaterialPicker.vue'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

const articleId = computed<number | null>(() => {
  const raw = route.params.id
  const id = Array.isArray(raw) ? raw[0] : raw
  return id ? Number(id) : null
})
const isEdit = computed(() => articleId.value != null)

// 可选公众号 (来自 auth.visibleMp)
const mpOptions = computed(() => auth.visibleMp)

// ---------- 表单 ----------
const form = reactive<ArticlePayload & { id?: number }>({
  mp_account_id: undefined,
  title: '',
  author: '',
  digest: '',
  content_html: '',
  cover_material_id: undefined,
  style_template_id: undefined,
})
const coverUrl = ref('')
const status = ref<ArticleStatus>('TRANSFORMED')
const publishedUrl = ref('')

const formRef = ref<FormInstance>()
const rules: FormRules = {
  mp_account_id: [{ required: true, message: '请选择公众号', trigger: 'change' }],
  title: [
    { required: true, message: '请输入标题', trigger: 'blur' },
    { max: 64, message: '标题不超过 64 字', trigger: 'blur' },
  ],
}

// 仅 TRANSFORMED(待提审)或 REJECTED(已驳回)可编辑, 其余只读
const readonly = computed(() => status.value !== 'TRANSFORMED' && status.value !== 'REJECTED')

// 图文状态标签与颜色(权威状态机)
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
const statusMeta = computed(
  () => STATUS_META[status.value] || { label: status.value || '-', type: 'info' as const },
)

// 可提审: 状态 ∈ {TRANSFORMED, REJECTED}
const canSubmit = computed(
  () => status.value === 'TRANSFORMED' || status.value === 'REJECTED',
)

const styleTemplates = ref<StyleTemplate[]>([])
async function loadStyleTemplates() {
  try {
    styleTemplates.value = await apiListStyleTemplates()
  } catch {
    styleTemplates.value = []
  }
}

const loading = ref(false)
async function loadArticle() {
  if (!articleId.value) return
  loading.value = true
  try {
    const a = await apiGetArticle(articleId.value)
    form.id = a.id
    form.mp_account_id = a.mp_account_id
    form.title = a.title
    form.author = a.author || ''
    form.digest = a.digest || ''
    form.content_html = a.content_html || ''
    form.cover_material_id = a.cover_material_id
    form.style_template_id = a.style_template_id
    coverUrl.value = (a.cover_url as string) || ''
    status.value = a.status || 'TRANSFORMED'
    publishedUrl.value = (a.published_url as string) || ''
  } finally {
    loading.value = false
  }
}

// ---------- 素材: 封面 / 正文插图 ----------
const editorRef = ref<InstanceType<typeof RichEditor>>()
const pickerVisible = ref(false)
const pickerTarget = ref<'cover' | 'content'>('cover')

function openCoverPicker() {
  pickerTarget.value = 'cover'
  pickerVisible.value = true
}
function openContentPicker() {
  pickerTarget.value = 'content'
  pickerVisible.value = true
}
function onPickMaterial(m: Material) {
  if (pickerTarget.value === 'cover') {
    form.cover_material_id = m.id
    coverUrl.value = m.url
  } else {
    editorRef.value?.insertImage(m.url, m.id, m.file_name || '')
  }
}
function clearCover() {
  form.cover_material_id = undefined
  coverUrl.value = ''
}

// ---------- 保存 ----------
const saving = ref(false)
function buildPayload(): ArticlePayload {
  return {
    mp_account_id: form.mp_account_id,
    title: form.title,
    author: form.author || undefined,
    digest: form.digest || undefined,
    content_html: form.content_html || '',
    cover_material_id: form.cover_material_id,
    style_template_id: form.style_template_id,
  }
}

// 返回保存后的 id
async function doSave(): Promise<number | null> {
  if (!formRef.value) return null
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return null
  saving.value = true
  try {
    if (isEdit.value && form.id) {
      await apiUpdateArticle(form.id, buildPayload())
      ElMessage.success('已保存')
      return form.id
    } else {
      const created = await apiCreateArticle(buildPayload())
      ElMessage.success('创建成功')
      // 创建后跳到编辑态, 保持在页面继续编辑
      router.replace({ name: 'article-edit', params: { id: created.id } })
      return created.id
    }
  } finally {
    saving.value = false
  }
}

// ---------- 提审 ----------
const submitting = ref(false)
async function onSubmitAudit() {
  const id = await doSave()
  if (!id) return
  try {
    await ElMessageBox.confirm('提交审核后将进入待审核状态, 期间不可编辑, 确认提交?', '提交审核', {
      type: 'warning',
      confirmButtonText: '提交',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  submitting.value = true
  try {
    const a = await apiSubmitArticle(id)
    status.value = a.status || 'PENDING_REVIEW'
    ElMessage.success('已提交审核')
  } finally {
    submitting.value = false
  }
}

// ---------- 版本历史 ----------
const versionVisible = ref(false)
const versionLoading = ref(false)
const versions = ref<ArticleVersion[]>([])
async function openVersions() {
  if (!form.id) {
    ElMessage.info('请先保存后再查看版本')
    return
  }
  versionVisible.value = true
  versionLoading.value = true
  try {
    versions.value = await apiListArticleVersions(form.id)
  } finally {
    versionLoading.value = false
  }
}
async function onRollback(v: ArticleVersion) {
  if (!form.id) return
  try {
    await ElMessageBox.confirm(`确定回滚到版本 v${v.version_no}? 当前未保存内容将丢失。`, '回滚版本', {
      type: 'warning',
      confirmButtonText: '回滚',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  await apiRollbackArticle(form.id, v.version_no)
  ElMessage.success('已回滚')
  versionVisible.value = false
  await loadArticle()
}

function goBack() {
  router.push({ name: 'articles' })
}

onMounted(async () => {
  await Promise.all([loadStyleTemplates(), loadArticle()])
})
</script>

<template>
  <div class="page-container" v-loading="loading">
    <div class="editor-header">
      <div class="left">
        <el-button link @click="goBack">
          <el-icon><ArrowLeft /></el-icon>返回列表
        </el-button>
        <span class="editor-title">{{ isEdit ? '编辑图文' : '新建图文' }}</span>
        <el-tag v-if="isEdit" size="small" class="status-tag" :type="statusMeta.type">
          {{ statusMeta.label }}
        </el-tag>
      </div>
      <div class="right">
        <el-button v-if="isEdit" @click="openVersions">
          <el-icon><Clock /></el-icon>版本历史
        </el-button>
        <el-button
          type="primary"
          plain
          :loading="saving"
          :disabled="readonly"
          @click="doSave"
        >
          保存草稿
        </el-button>
        <el-button
          v-if="!isEdit || canSubmit"
          type="primary"
          :loading="submitting"
          :disabled="readonly"
          @click="onSubmitAudit"
        >
          保存并提审
        </el-button>
      </div>
    </div>

    <el-alert
      v-if="publishedUrl"
      type="success"
      :closable="false"
      class="pub-alert"
      show-icon
    >
      <template #title>
        已发布:
        <el-link type="primary" :href="publishedUrl" target="_blank">{{ publishedUrl }}</el-link>
      </template>
    </el-alert>

    <el-form
      ref="formRef"
      :model="form"
      :rules="rules"
      label-width="90px"
      :disabled="readonly"
      class="editor-form"
    >
      <el-row :gutter="16">
        <el-col :span="12">
          <el-form-item label="公众号" prop="mp_account_id">
            <el-select
              v-model="form.mp_account_id"
              placeholder="选择公众号"
              style="width: 100%"
              filterable
            >
              <el-option
                v-for="mp in mpOptions"
                :key="mp.id"
                :label="mp.mp_name"
                :value="mp.id"
              />
            </el-select>
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="样式模板">
            <el-select
              v-model="form.style_template_id"
              placeholder="选择样式模板 (可选)"
              style="width: 100%"
              clearable
            >
              <el-option
                v-for="t in styleTemplates"
                :key="t.id"
                :label="t.template_name"
                :value="t.id"
              />
            </el-select>
          </el-form-item>
        </el-col>
      </el-row>

      <el-form-item label="标题" prop="title">
        <el-input v-model="form.title" placeholder="图文标题" maxlength="64" show-word-limit />
      </el-form-item>

      <el-row :gutter="16">
        <el-col :span="12">
          <el-form-item label="作者">
            <el-input v-model="form.author" placeholder="作者 (可选)" maxlength="20" />
          </el-form-item>
        </el-col>
      </el-row>

      <el-form-item label="摘要">
        <el-input
          v-model="form.digest"
          type="textarea"
          :rows="2"
          maxlength="120"
          show-word-limit
          placeholder="图文摘要 (可选, 不填则取正文前若干字)"
        />
      </el-form-item>

      <el-form-item label="封面">
        <div class="cover-box">
          <div v-if="coverUrl" class="cover-preview">
            <el-image :src="coverUrl" fit="cover" class="cover-img" />
            <div class="cover-actions">
              <el-button link type="primary" :disabled="readonly" @click="openCoverPicker">
                更换
              </el-button>
              <el-button link type="danger" :disabled="readonly" @click="clearCover">
                移除
              </el-button>
            </div>
          </div>
          <el-button v-else :disabled="readonly" @click="openCoverPicker">
            <el-icon><Picture /></el-icon>从素材库选择封面
          </el-button>
        </div>
      </el-form-item>

      <el-form-item label="正文">
        <div class="body-wrap">
          <div class="body-toolbar">
            <el-button size="small" :disabled="readonly" @click="openContentPicker">
              <el-icon><Picture /></el-icon>插入素材图
            </el-button>
          </div>
          <RichEditor
            ref="editorRef"
            v-model="form.content_html"
            :mp-account-id="form.mp_account_id"
            height="460px"
          />
        </div>
      </el-form-item>
    </el-form>

    <!-- 素材选择 -->
    <MaterialPicker
      v-model="pickerVisible"
      :mp-account-id="form.mp_account_id"
      @pick="onPickMaterial"
    />

    <!-- 版本历史 -->
    <el-drawer v-model="versionVisible" title="版本历史" size="480px">
      <el-timeline v-loading="versionLoading">
        <el-timeline-item
          v-for="v in versions"
          :key="v.id"
          :timestamp="v.created_at"
          placement="top"
        >
          <div class="ver-item">
            <div class="ver-head">
              <b>v{{ v.version_no }}</b>
              <span v-if="v.created_by" class="muted">by {{ v.created_by }}</span>
            </div>
            <div v-if="v.title" class="ver-title">{{ v.title }}</div>
            <div v-if="v.change_note" class="muted">{{ v.change_note }}</div>
            <el-button
              link
              type="primary"
              size="small"
              :disabled="readonly"
              @click="onRollback(v)"
            >
              回滚到此版本
            </el-button>
          </div>
        </el-timeline-item>
      </el-timeline>
      <el-empty v-if="!versionLoading && !versions.length" description="暂无历史版本" />
    </el-drawer>
  </div>
</template>

<style scoped>
.editor-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
  gap: 12px;
  flex-wrap: wrap;
}
.editor-header .left {
  display: flex;
  align-items: center;
  gap: 10px;
}
.editor-title {
  font-size: 16px;
  font-weight: 600;
}
.status-tag {
  text-transform: uppercase;
}
.pub-alert {
  margin-bottom: 16px;
}
.editor-form {
  background: #fff;
  padding: 20px 24px 8px;
  border-radius: 8px;
}
.cover-box {
  width: 100%;
}
.cover-preview {
  display: flex;
  align-items: flex-end;
  gap: 12px;
}
.cover-img {
  width: 180px;
  height: 110px;
  border-radius: 6px;
  border: 1px solid #ebeef5;
}
.cover-actions {
  display: flex;
  flex-direction: column;
}
.body-wrap {
  width: 100%;
}
.body-toolbar {
  margin-bottom: 8px;
}
.ver-item {
  padding-bottom: 4px;
}
.ver-head {
  display: flex;
  align-items: center;
  gap: 8px;
}
.ver-title {
  margin: 2px 0;
  color: #303133;
}
.muted {
  color: #909399;
  font-size: 12px;
}
</style>
