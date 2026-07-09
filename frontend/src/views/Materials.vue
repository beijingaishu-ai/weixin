<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { UploadRawFile } from 'element-plus'
import { apiDeleteMaterial, apiListMaterials, apiUploadMaterial } from '@/api/modules'
import { useAuthStore } from '@/stores/auth'
import type { Material } from '@/api/types'

const auth = useAuthStore()
// 有台账编辑权限或用户管理即可维护素材; view 权限仅浏览
const canEdit = computed(
  () => auth.hasPerm('content:material:edit') || auth.hasPerm('user:manage'),
)

const loading = ref(false)
const list = ref<Material[]>([])
const total = ref(0)
const query = reactive({ page: 1, page_size: 12, keyword: '' })

function humanSize(n?: number): string {
  if (!n) return '-'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(2)} MB`
}

async function loadList() {
  loading.value = true
  try {
    const data = await apiListMaterials({ ...query, keyword: query.keyword || undefined })
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
  query.page = 1
  loadList()
}

// ---------- 上传 ----------
const uploading = ref(false)
const uploadPercent = ref(0)
async function beforeUpload(raw: UploadRawFile) {
  const isImage = raw.type.startsWith('image/')
  if (!isImage) {
    ElMessage.warning('仅支持上传图片素材')
    return false
  }
  const maxMB = 10
  if (raw.size / 1024 / 1024 > maxMB) {
    ElMessage.warning(`图片不能超过 ${maxMB}MB`)
    return false
  }
  uploading.value = true
  uploadPercent.value = 0
  try {
    await apiUploadMaterial(raw, { type: 'image' }, (p) => (uploadPercent.value = p))
    ElMessage.success('上传成功')
    query.page = 1
    await loadList()
  } finally {
    uploading.value = false
  }
  // 阻止 el-upload 默认上传行为
  return false
}

// ---------- 删除 ----------
async function onDelete(m: Material) {
  try {
    await ElMessageBox.confirm(`确定删除素材「${m.file_name || '#' + m.id}」?`, '提示', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  await apiDeleteMaterial(m.id)
  ElMessage.success('已删除')
  // 删除后若当前页空了, 回退一页
  if (list.value.length === 1 && query.page > 1) query.page -= 1
  loadList()
}

// ---------- 预览 ----------
const previewUrl = ref('')
const previewVisible = ref(false)
function onPreview(m: Material) {
  previewUrl.value = m.url
  previewVisible.value = true
}

onMounted(loadList)
</script>

<template>
  <div class="page-container">
    <div class="page-toolbar">
      <div class="left">
        <el-input
          v-model="query.keyword"
          placeholder="搜索素材文件名"
          clearable
          style="width: 220px"
          @keyup.enter="onSearch"
          @clear="onReset"
        />
        <el-button type="primary" @click="onSearch">
          <el-icon><Search /></el-icon>搜索
        </el-button>
        <el-button @click="onReset">重置</el-button>
      </div>
      <div class="right">
        <el-upload
          v-if="canEdit"
          :show-file-list="false"
          :before-upload="beforeUpload"
          accept="image/*"
        >
          <el-button type="primary" :loading="uploading">
            <el-icon><Upload /></el-icon>上传素材
          </el-button>
        </el-upload>
      </div>
    </div>

    <el-progress
      v-if="uploading"
      :percentage="uploadPercent"
      :stroke-width="6"
      style="margin-bottom: 12px"
    />

    <div v-loading="loading" class="mat-grid">
      <div v-for="m in list" :key="m.id" class="mat-card">
        <div class="mat-thumb" @click="onPreview(m)">
          <el-image :src="m.url" fit="cover" class="mat-img" lazy>
            <template #error>
              <div class="img-err"><el-icon><Picture /></el-icon></div>
            </template>
          </el-image>
        </div>
        <div class="mat-meta">
          <div class="mat-name" :title="m.file_name">{{ m.file_name || '#' + m.id }}</div>
          <div class="mat-sub">
            <span>{{ humanSize(m.size) }}</span>
            <el-button
              v-if="canEdit"
              link
              type="danger"
              size="small"
              @click="onDelete(m)"
            >
              删除
            </el-button>
          </div>
        </div>
      </div>
      <el-empty
        v-if="!loading && !list.length"
        description="暂无素材, 点击右上角上传"
        :image-size="100"
      />
    </div>

    <div class="pager">
      <el-pagination
        v-model:current-page="query.page"
        v-model:page-size="query.page_size"
        :total="total"
        :page-sizes="[12, 24, 48]"
        layout="total, sizes, prev, pager, next, jumper"
        background
        @current-change="loadList"
        @size-change="onSearch"
      />
    </div>

    <el-dialog v-model="previewVisible" title="素材预览" width="640px">
      <el-image :src="previewUrl" fit="contain" style="width: 100%; max-height: 70vh" />
    </el-dialog>
  </div>
</template>

<style scoped>
.pager {
  margin-top: 16px;
  display: flex;
  justify-content: flex-end;
}
.mat-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 16px;
  min-height: 240px;
}
.mat-card {
  border: 1px solid #ebeef5;
  border-radius: 8px;
  background: #fff;
  overflow: hidden;
  transition: box-shadow 0.15s;
}
.mat-card:hover {
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
}
.mat-thumb {
  cursor: zoom-in;
}
.mat-img {
  width: 100%;
  height: 150px;
  display: block;
  background: #f5f7fa;
}
.img-err {
  height: 150px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #c0c4cc;
  font-size: 32px;
}
.mat-meta {
  padding: 8px 10px;
}
.mat-name {
  font-size: 13px;
  color: #303133;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.mat-sub {
  margin-top: 4px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12px;
  color: #909399;
}
</style>
