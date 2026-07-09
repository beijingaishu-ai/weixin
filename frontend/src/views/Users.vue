<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import {
  apiCreateUser,
  apiListRoles,
  apiListUsers,
  apiResetPassword,
  apiSetUserRoles,
  apiUpdateUser,
  type CreateUserPayload,
} from '@/api/modules'
import type { RoleItem, UserItem } from '@/api/types'

const loading = ref(false)
const list = ref<UserItem[]>([])
const total = ref(0)
const query = reactive({ page: 1, page_size: 10, keyword: '' })
const roles = ref<RoleItem[]>([])

async function loadRoles() {
  try {
    roles.value = await apiListRoles()
  } catch {
    /* ignore */
  }
}

async function loadList() {
  loading.value = true
  try {
    const data = await apiListUsers({ ...query })
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

// ---------- 新建 / 编辑 ----------
const editVisible = ref(false)
const editMode = ref<'create' | 'edit'>('create')
const editForm = reactive({
  id: 0,
  username: '',
  real_name: '',
  password: '',
  role_code: '',
  is_active: true,
})
const editFormRef = ref<FormInstance>()
const editRules: FormRules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  real_name: [{ required: true, message: '请输入姓名', trigger: 'blur' }],
  role_code: [
    {
      validator: (_r, val, cb) => {
        if (editMode.value === 'create' && !val) cb(new Error('请选择角色'))
        else cb()
      },
      trigger: 'change',
    },
  ],
  password: [
    {
      validator: (_r, val, cb) => {
        if (editMode.value === 'create' && !val) cb(new Error('请输入初始密码(至少6位)'))
        else if (editMode.value === 'create' && val.length < 6) cb(new Error('密码至少6位'))
        else cb()
      },
      trigger: 'blur',
    },
  ],
}

function openCreate() {
  editMode.value = 'create'
  Object.assign(editForm, {
    id: 0,
    username: '',
    real_name: '',
    password: '',
    role_code: '',
    is_active: true,
  })
  editVisible.value = true
}
function openEdit(row: UserItem) {
  editMode.value = 'edit'
  Object.assign(editForm, {
    id: row.id,
    username: row.username,
    real_name: row.real_name,
    password: '',
    role_code: '',
    is_active: row.status === undefined ? row.is_active ?? true : row.status === 1,
  })
  editVisible.value = true
}

const saving = ref(false)
async function submitEdit() {
  if (!editFormRef.value) return
  const valid = await editFormRef.value.validate().catch(() => false)
  if (!valid) return
  saving.value = true
  try {
    if (editMode.value === 'create') {
      const payload: CreateUserPayload = {
        username: editForm.username,
        real_name: editForm.real_name,
        password: editForm.password,
        role_code: editForm.role_code,
      }
      await apiCreateUser(payload)
      ElMessage.success('创建成功')
    } else {
      await apiUpdateUser(editForm.id, {
        real_name: editForm.real_name,
        status: editForm.is_active ? 1 : 0,
      })
      ElMessage.success('更新成功')
    }
    editVisible.value = false
    loadList()
  } finally {
    saving.value = false
  }
}

// ---------- 设置角色 ----------
const roleVisible = ref(false)
const roleTargetUser = ref<UserItem | null>(null)
const selectedRoleCodes = ref<string[]>([])
const roleSaving = ref(false)

function openRoles(row: UserItem) {
  roleTargetUser.value = row
  // 当前角色来自列表返回的 roles(role_code 数组)
  selectedRoleCodes.value = [...((row.roles as string[] | undefined) || [])]
  roleVisible.value = true
}
async function submitRoles() {
  if (!roleTargetUser.value) return
  if (!selectedRoleCodes.value.length) {
    ElMessage.warning('至少选择一个角色')
    return
  }
  roleSaving.value = true
  try {
    await apiSetUserRoles(roleTargetUser.value.id, selectedRoleCodes.value)
    ElMessage.success('角色已更新')
    roleVisible.value = false
    loadList()
  } finally {
    roleSaving.value = false
  }
}

// ---------- 重置密码 ----------
const pwdVisible = ref(false)
const pwdTargetUser = ref<UserItem | null>(null)
const pwdForm = reactive({ password: '' })
const pwdFormRef = ref<FormInstance>()
const pwdRules: FormRules = {
  password: [{ required: true, message: '请输入新密码(至少6位)', trigger: 'blur' }],
}
const pwdSaving = ref(false)

function openResetPwd(row: UserItem) {
  pwdTargetUser.value = row
  pwdForm.password = ''
  pwdVisible.value = true
}
async function submitPwd() {
  if (!pwdFormRef.value || !pwdTargetUser.value) return
  const valid = await pwdFormRef.value.validate().catch(() => false)
  if (!valid) return
  pwdSaving.value = true
  try {
    await apiResetPassword(pwdTargetUser.value.id, pwdForm.password)
    ElMessage.success('密码已重置')
    pwdVisible.value = false
  } finally {
    pwdSaving.value = false
  }
}

function roleLabel(code: string): string {
  return roles.value.find((r) => r.role_code === code)?.role_name || code
}

onMounted(() => {
  loadRoles()
  loadList()
})
</script>

<template>
  <div class="page-container">
    <div class="page-toolbar">
      <div class="left">
        <el-input
          v-model="query.keyword"
          placeholder="搜索用户名/姓名"
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
        <el-button type="primary" @click="openCreate">
          <el-icon><Plus /></el-icon>新建用户
        </el-button>
      </div>
    </div>

    <el-table v-loading="loading" :data="list" border stripe>
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column prop="username" label="用户名" min-width="120" />
      <el-table-column prop="real_name" label="姓名" min-width="120" />
      <el-table-column label="角色" min-width="180">
        <template #default="{ row }">
          <template v-if="row.roles && row.roles.length">
            <el-tag v-for="r in row.roles" :key="r" size="small" class="tag-gap">
              {{ roleLabel(r) }}
            </el-tag>
          </template>
          <span v-else class="muted">-</span>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag :type="row.status === 0 ? 'danger' : 'success'" size="small">
            {{ row.status === 0 ? '停用' : '正常' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="created_at" label="创建时间" min-width="160" />
      <el-table-column label="操作" width="300" fixed="right">
        <template #default="scope">
          <el-button link type="primary" @click="openEdit(scope.row as UserItem)">编辑</el-button>
          <el-button link type="primary" @click="openRoles(scope.row as UserItem)">设角色</el-button>
          <el-button link type="warning" @click="openResetPwd(scope.row as UserItem)">
            重置密码
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
      :title="editMode === 'create' ? '新建用户' : '编辑用户'"
      width="480px"
    >
      <el-form ref="editFormRef" :model="editForm" :rules="editRules" label-width="90px">
        <el-form-item label="用户名" prop="username">
          <el-input
            v-model="editForm.username"
            :disabled="editMode === 'edit'"
            placeholder="登录用户名"
          />
        </el-form-item>
        <el-form-item label="姓名" prop="real_name">
          <el-input v-model="editForm.real_name" placeholder="真实姓名" />
        </el-form-item>
        <el-form-item v-if="editMode === 'create'" label="角色" prop="role_code">
          <el-select v-model="editForm.role_code" placeholder="请选择角色" style="width: 100%">
            <el-option
              v-for="r in roles"
              :key="r.role_code"
              :label="r.role_name"
              :value="r.role_code"
            />
          </el-select>
        </el-form-item>
        <el-form-item v-if="editMode === 'create'" label="初始密码" prop="password">
          <el-input
            v-model="editForm.password"
            type="password"
            show-password
            placeholder="初始密码(至少6位)"
          />
        </el-form-item>
        <el-form-item v-if="editMode === 'edit'" label="状态">
          <el-switch v-model="editForm.is_active" active-text="正常" inactive-text="停用" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submitEdit">确定</el-button>
      </template>
    </el-dialog>

    <!-- 设角色 -->
    <el-dialog v-model="roleVisible" title="设置角色" width="480px">
      <p class="dialog-sub">
        用户: <b>{{ roleTargetUser?.real_name }}</b> ({{ roleTargetUser?.username }})
      </p>
      <el-checkbox-group v-model="selectedRoleCodes">
        <el-checkbox
          v-for="r in roles"
          :key="r.role_code"
          :value="r.role_code"
          :label="r.role_code"
          class="role-checkbox"
        >
          {{ r.role_name }}<span class="muted"> ({{ r.role_code }})</span>
        </el-checkbox>
      </el-checkbox-group>
      <el-empty v-if="!roles.length" description="暂无可分配角色" :image-size="60" />
      <template #footer>
        <el-button @click="roleVisible = false">取消</el-button>
        <el-button type="primary" :loading="roleSaving" @click="submitRoles">保存</el-button>
      </template>
    </el-dialog>

    <!-- 重置密码 -->
    <el-dialog v-model="pwdVisible" title="重置密码" width="420px">
      <p class="dialog-sub">
        用户: <b>{{ pwdTargetUser?.real_name }}</b> ({{ pwdTargetUser?.username }})
      </p>
      <el-form ref="pwdFormRef" :model="pwdForm" :rules="pwdRules" label-width="80px">
        <el-form-item label="新密码" prop="password">
          <el-input
            v-model="pwdForm.password"
            type="password"
            show-password
            placeholder="请输入新密码(至少6位)"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="pwdVisible = false">取消</el-button>
        <el-button type="primary" :loading="pwdSaving" @click="submitPwd">确定</el-button>
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
.tag-gap {
  margin-right: 4px;
}
.muted {
  color: #909399;
}
.dialog-sub {
  margin: 0 0 16px;
  color: #606266;
}
.role-checkbox {
  display: block;
  margin: 0 0 10px;
}
</style>
