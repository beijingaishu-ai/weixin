<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { apiListAudit } from '@/api/modules'
import type { AuditRecord } from '@/api/types'

const loading = ref(false)
const list = ref<AuditRecord[]>([])
const total = ref(0)
const query = reactive({ page: 1, page_size: 20, keyword: '' })

async function loadList() {
  loading.value = true
  try {
    const data = await apiListAudit({ ...query })
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

onMounted(loadList)
</script>

<template>
  <div class="page-container">
    <div class="page-toolbar">
      <div class="left">
        <el-input
          v-model="query.keyword"
          placeholder="搜索操作人/动作/目标"
          clearable
          style="width: 240px"
          @keyup.enter="onSearch"
          @clear="onReset"
        />
        <el-button type="primary" @click="onSearch">
          <el-icon><Search /></el-icon>搜索
        </el-button>
        <el-button @click="onReset">重置</el-button>
      </div>
    </div>

    <el-table v-loading="loading" :data="list" border stripe>
      <el-table-column prop="id" label="ID" width="80" />
      <el-table-column label="操作人" min-width="140">
        <template #default="{ row }">
          {{ row.operator || row.user_id || '-' }}
        </template>
      </el-table-column>
      <el-table-column prop="action" label="动作" min-width="140">
        <template #default="{ row }">
          <el-tag size="small" type="info">{{ row.action || '-' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="target" label="目标" min-width="160" show-overflow-tooltip />
      <el-table-column prop="detail" label="详情" min-width="220" show-overflow-tooltip />
      <el-table-column prop="ip" label="IP" min-width="130" />
      <el-table-column prop="created_at" label="时间" min-width="170" />
    </el-table>

    <div class="pager">
      <el-pagination
        v-model:current-page="query.page"
        v-model:page-size="query.page_size"
        :total="total"
        :page-sizes="[20, 50, 100]"
        layout="total, sizes, prev, pager, next, jumper"
        background
        @current-change="loadList"
        @size-change="onSearch"
      />
    </div>
  </div>
</template>

<style scoped>
.pager {
  margin-top: 16px;
  display: flex;
  justify-content: flex-end;
}
</style>
