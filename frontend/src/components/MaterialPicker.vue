<script setup lang="ts">
/**
 * 素材选择对话框 (从素材库挑一张图)
 * 用于: 图文封面选择、正文插图。
 * 用法: <MaterialPicker v-model="visible" @pick="onPick" />
 */
import { ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { apiListMaterials, apiUploadMaterial } from '@/api/modules'
import type { Material } from '@/api/types'
import type { UploadRawFile } from 'element-plus'

const props = withDefaults(
  defineProps<{
    modelValue: boolean
    mpAccountId?: number
  }>(),
  { modelValue: false },
)
const emit = defineEmits<{
  (e: 'update:modelValue', v: boolean): void
  (e: 'pick', material: Material): void
}>()

const visible = ref(props.modelValue)
watch(
  () => props.modelValue,
  (v) => {
    visible.value = v
    if (v) loadList()
  },
)
watch(visible, (v) => emit('update:modelValue', v))

const loading = ref(false)
const list = ref<Material[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(12)
const keyword = ref('')

async function loadList() {
  loading.value = true
  try {
    const data = await apiListMaterials({
      page: page.value,
      page_size: pageSize.value,
      keyword: keyword.value || undefined,
      type: 'image',
      mp_account_id: props.mpAccountId,
    })
    list.value = data.items
    total.value = data.total
  } finally {
    loading.value = false
  }
}

function onSearch() {
  page.value = 1
  loadList()
}

const uploading = ref(false)
async function onUpload(raw: UploadRawFile) {
  uploading.value = true
  try {
    await apiUploadMaterial(raw, { mp_account_id: props.mpAccountId, type: 'image' })
    ElMessage.success('上传成功')
    page.value = 1
    await loadList()
  } finally {
    uploading.value = false
  }
  return false
}

function pick(m: Material) {
  emit('pick', m)
  visible.value = false
}
</script>

<template>
  <el-dialog v-model="visible" title="选择素材" width="720px" top="6vh">
    <div class="picker-toolbar">
      <el-input
        v-model="keyword"
        placeholder="搜索文件名"
        clearable
        style="width: 200px"
        @keyup.enter="onSearch"
        @clear="onSearch"
      />
      <el-button type="primary" @click="onSearch">搜索</el-button>
      <el-upload
        class="picker-upload"
        :show-file-list="false"
        :before-upload="onUpload"
        accept="image/*"
      >
        <el-button :loading="uploading" type="success" plain>上传新素材</el-button>
      </el-upload>
    </div>

    <div v-loading="loading" class="picker-grid">
      <div
        v-for="m in list"
        :key="m.id"
        class="picker-item"
        @click="pick(m)"
      >
        <el-image :src="m.url" fit="cover" class="picker-img" lazy>
          <template #error>
            <div class="img-err"><el-icon><Picture /></el-icon></div>
          </template>
        </el-image>
        <div class="picker-name" :title="m.file_name">{{ m.file_name || ('#' + m.id) }}</div>
      </div>
      <el-empty v-if="!loading && !list.length" description="暂无素材" :image-size="80" />
    </div>

    <div class="picker-pager">
      <el-pagination
        v-model:current-page="page"
        :page-size="pageSize"
        :total="total"
        layout="total, prev, pager, next"
        background
        small
        @current-change="loadList"
      />
    </div>
  </el-dialog>
</template>

<style scoped>
.picker-toolbar {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-bottom: 12px;
}
.picker-upload {
  margin-left: auto;
}
.picker-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  min-height: 200px;
}
.picker-item {
  border: 1px solid #ebeef5;
  border-radius: 6px;
  overflow: hidden;
  cursor: pointer;
  transition: box-shadow 0.15s, border-color 0.15s;
}
.picker-item:hover {
  border-color: #409eff;
  box-shadow: 0 2px 8px rgba(64, 158, 255, 0.25);
}
.picker-img {
  width: 100%;
  height: 120px;
  display: block;
  background: #f5f7fa;
}
.img-err {
  height: 120px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #c0c4cc;
  font-size: 28px;
}
.picker-name {
  padding: 4px 6px;
  font-size: 12px;
  color: #606266;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.picker-pager {
  margin-top: 12px;
  display: flex;
  justify-content: flex-end;
}
</style>
