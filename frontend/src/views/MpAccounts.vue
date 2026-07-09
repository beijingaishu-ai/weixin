<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import {
  apiCreateMpAccount,
  apiGetAssignees,
  apiGetLoginAuth,
  apiListMpAccounts,
  apiListUsers,
  apiRevokeLoginAuth,
  apiSetAssignees,
  apiUpdateMpAccount,
  apiVerifyMpAccount,
  type CreateMpPayload,
  type VerifyResult,
} from '@/api/modules'
import { useAuthStore } from '@/stores/auth'
import type { MpAccount, UserItem } from '@/api/types'

const auth = useAuthStore()
const canEdit = computed(() => auth.hasPerm('mp:account:manage'))
const canAssign = computed(() => auth.hasPerm('user:assign'))

// perm_level 与后端一致:整数 1-4,逐级包含
const PERM_LEVELS = [
  { value: 1, label: '只读' },
  { value: 2, label: '编辑' },
  { value: 3, label: '编辑+提审' },
  { value: 4, label: '可发布' },
]

const ACCOUNT_TYPES = [
  { value: 1, label: '订阅号' },
  { value: 2, label: '服务号' },
  { value: 3, label: '测试/模拟号(走 MockChannel,无需真实 AppSecret)' },
]

const loading = ref(false)
const list = ref<MpAccount[]>([])
const total = ref(0)
const query = reactive({ page: 1, page_size: 10, keyword: '' })

async function loadList() {
  loading.value = true
  try {
    const data = await apiListMpAccounts({ ...query })
    list.value = data.items
    total.value = data.total
  } finally {
    loading.value = false
  }
}
// 浏览器发布登录态授权:状态 → 标签(仅真实号;Mock 号 account_type=3 无需授权)
function loginAuthTag(row: MpAccount): { type: 'success' | 'warning' | 'danger' | 'info'; text: string } {
  if (row.account_type === 3) return { type: 'info', text: 'Mock' }
  const s = String(row.wx_login_status || 'UNAUTHORIZED')
  const base: Record<string, { type: 'success' | 'warning' | 'danger' | 'info'; text: string }> = {
    AUTHORIZED: { type: 'success', text: '已授权' },
    EXPIRING: { type: 'warning', text: '临期' },
    EXPIRED: { type: 'danger', text: '需续扫' },
    REVOKED: { type: 'danger', text: '需续扫' },
    UNAUTHORIZED: { type: 'info', text: '未授权' },
  }
  const b = base[s] || { type: 'info' as const, text: s }
  if ((s === 'AUTHORIZED' || s === 'EXPIRING') && row.wx_login_expires_at) {
    // 后端 expires_at 为 UTC naive,补 'Z' 让浏览器按 UTC 解析,倒计时不受客户端时区影响
    const ms = new Date(String(row.wx_login_expires_at) + 'Z').getTime() - Date.now()
    return { type: b.type, text: `${b.text}·剩${Math.max(0, Math.round(ms / 3.6e6))}h` }
  }
  return b
}

// 续扫入口:展示状态 + 部署机扫码命令;可选吊销当前登录态
async function onReauth(row: MpAccount) {
  const s = await apiGetLoginAuth(row.id)
  if (s.is_mock) {
    ElMessage.info('测试/模拟号(account_type=3)走 Mock,无需登录态授权')
    return
  }
  const html =
    `<div>当前状态:<b>${s.wx_login_status}</b></div>` +
    `<div>到期:${s.wx_login_expires_at ? String(s.wx_login_expires_at) + ' (UTC)' : '—'}</div>` +
    `<div style="margin:8px 0 4px">在部署机执行以下命令,用该号管理员微信扫码续期(有效 ${s.wx_login_ttl_hours}h):</div>` +
    `<pre style="background:#f5f5f5;padding:8px;border-radius:4px;white-space:pre-wrap">${s.reauth_cmd}</pre>`
  try {
    await ElMessageBox.confirm(html, '浏览器发布 · 扫码续期', {
      dangerouslyUseHTMLString: true,
      confirmButtonText: '知道了',
      cancelButtonText: '吊销当前登录态',
      distinguishCancelAndClose: true,
      type: 'info',
    })
  } catch (action) {
    if (action === 'cancel') {
      await apiRevokeLoginAuth(row.id)
      ElMessage.success('已吊销,下次发布前需重新扫码授权')
      loadList()
    }
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
  mp_name: '',
  account_type: 3,
  app_id: '',
  app_secret: '',
  remark: '',
})
const editFormRef = ref<FormInstance>()
const editRules: FormRules = {
  mp_name: [{ required: true, message: '请输入公众号名称', trigger: 'blur' }],
  app_id: [{ required: true, message: '请输入 AppID', trigger: 'blur' }],
  app_secret: [
    {
      validator: (_r, val, cb) => {
        // 测试/模拟号(account_type=3)走 Mock,AppSecret 可留空
        if (editMode.value === 'create' && editForm.account_type !== 3 && !val)
          cb(new Error('请输入 AppSecret'))
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
    mp_name: '',
    account_type: 3,
    app_id: '',
    app_secret: '',
    remark: '',
  })
  editVisible.value = true
}
function openEdit(row: MpAccount) {
  editMode.value = 'edit'
  Object.assign(editForm, {
    id: row.id,
    mp_name: row.mp_name,
    account_type: (row.account_type as number) ?? 1,
    app_id: row.app_id || '',
    app_secret: '', // 编辑时留空表示不修改
    remark: row.remark || '',
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
      const payload: CreateMpPayload = {
        mp_name: editForm.mp_name,
        account_type: editForm.account_type,
        app_id: editForm.app_id,
        // 模拟号 AppSecret 可留空,填占位值满足后端非空校验(MockChannel 不使用)
        app_secret:
          editForm.account_type === 3
            ? editForm.app_secret || 'MOCK_SECRET'
            : editForm.app_secret,
        remark: editForm.remark || undefined,
      }
      await apiCreateMpAccount(payload)
      ElMessage.success('创建成功')
    } else {
      const payload: Partial<MpAccount> = {
        mp_name: editForm.mp_name,
        app_id: editForm.app_id,
        remark: editForm.remark,
      }
      if (editForm.app_secret) payload.app_secret = editForm.app_secret
      await apiUpdateMpAccount(editForm.id, payload)
      ElMessage.success('更新成功')
    }
    editVisible.value = false
    loadList()
  } finally {
    saving.value = false
  }
}

// ---------- 校验凭据 ----------
const verifyingId = ref<number | null>(null)
const verifyVisible = ref(false)
const verifyResult = ref<VerifyResult | null>(null)
const verifyMpName = ref('')

async function onVerify(row: MpAccount) {
  verifyingId.value = row.id
  verifyMpName.value = row.mp_name
  try {
    const res = await apiVerifyMpAccount(row.id)
    verifyResult.value = res
    verifyVisible.value = true
    loadList() // 校验后 ip_whitelist_ok 可能变化
  } finally {
    verifyingId.value = null
  }
}

// ---------- 分配运营 ----------
const assignVisible = ref(false)
const assignMp = ref<MpAccount | null>(null)
const allUsers = ref<UserItem[]>([])
// transfer 右侧选中的 user_id
const assignedUserIds = ref<number[]>([])
// user_id -> perm_level(整数 1-4)
const permMap = reactive<Record<number, number>>({})
const assignLoading = ref(false)
const assignSaving = ref(false)

const transferData = computed(() =>
  allUsers.value.map((u) => ({
    key: u.id,
    label: `${u.real_name || u.username}${u.username ? ' (' + u.username + ')' : ''}`,
  })),
)

// 右侧已选用户的明细 (用于每人配 perm_level)
const assignedDetails = computed(() =>
  assignedUserIds.value.map((uid) => {
    const u = allUsers.value.find((x) => x.id === uid)
    return {
      user_id: uid,
      name: u ? u.real_name || u.username : String(uid),
    }
  }),
)

async function openAssign(row: MpAccount) {
  assignMp.value = row
  assignVisible.value = true
  assignLoading.value = true
  assignedUserIds.value = []
  for (const k of Object.keys(permMap)) delete permMap[Number(k)]
  try {
    // 拉全量用户 (作为可分配池) + 当前分配
    const [usersPage, assignees] = await Promise.all([
      apiListUsers({ page: 1, page_size: 100 }),
      apiGetAssignees(row.id),
    ])
    allUsers.value = usersPage.items
    assignedUserIds.value = assignees.map((a) => a.user_id)
    assignees.forEach((a) => {
      permMap[a.user_id] = a.perm_level || 2
    })
  } finally {
    assignLoading.value = false
  }
}

// transfer 变化: 新增的人给默认 perm_level
function onTransferChange(targetKeys: (string | number)[]) {
  targetKeys.forEach((k) => {
    const id = Number(k)
    if (!permMap[id]) permMap[id] = 2
  })
}

async function submitAssign() {
  if (!assignMp.value) return
  // 全量覆盖提交
  const payload = assignedUserIds.value.map((uid) => ({
    user_id: uid,
    perm_level: permMap[uid] || 2,
  }))
  assignSaving.value = true
  try {
    await apiSetAssignees(assignMp.value.id, payload)
    ElMessage.success('运营分配已保存')
    assignVisible.value = false
    loadList()
  } finally {
    assignSaving.value = false
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
          placeholder="搜索公众号名称"
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
        <el-button v-if="canEdit" type="primary" @click="openCreate">
          <el-icon><Plus /></el-icon>新建公众号
        </el-button>
      </div>
    </div>

    <el-table v-loading="loading" :data="list" border stripe>
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column prop="mp_name" label="公众号名称" min-width="160" />
      <el-table-column prop="app_id" label="AppID" min-width="180" />
      <el-table-column label="IP 白名单" width="120" align="center">
        <template #default="{ row }">
          <el-tag :type="row.ip_whitelist_ok ? 'success' : 'danger'" size="small" effect="dark">
            {{ row.ip_whitelist_ok ? '正常' : '异常' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="校验状态" width="120">
        <template #default="{ row }">
          <span v-if="row.verify_status">{{ row.verify_status }}</span>
          <span v-else class="muted">-</span>
        </template>
      </el-table-column>
      <el-table-column label="发布授权" width="130" align="center">
        <template #default="{ row }">
          <el-tag :type="loginAuthTag(row as MpAccount).type" size="small" effect="plain">
            {{ loginAuthTag(row as MpAccount).text }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="remark" label="备注" min-width="140" show-overflow-tooltip />
      <el-table-column label="操作" width="300" fixed="right">
        <template #default="scope">
          <el-button
            link
            type="success"
            :loading="verifyingId === (scope.row as MpAccount).id"
            @click="onVerify(scope.row as MpAccount)"
          >
            校验凭据
          </el-button>
          <el-button
            v-if="(scope.row as MpAccount).account_type !== 3"
            link
            type="warning"
            @click="onReauth(scope.row as MpAccount)"
          >
            续扫
          </el-button>
          <el-button v-if="canEdit" link type="primary" @click="openEdit(scope.row as MpAccount)">
            编辑
          </el-button>
          <el-button
            v-if="canAssign"
            link
            type="primary"
            @click="openAssign(scope.row as MpAccount)"
          >
            分配运营
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
      :title="editMode === 'create' ? '新建公众号' : '编辑公众号'"
      width="520px"
    >
      <el-form ref="editFormRef" :model="editForm" :rules="editRules" label-width="100px">
        <el-form-item label="公众号名称" prop="mp_name">
          <el-input v-model="editForm.mp_name" placeholder="公众号名称" />
        </el-form-item>
        <el-form-item label="账号类型" prop="account_type">
          <el-select
            v-model="editForm.account_type"
            :disabled="editMode === 'edit'"
            style="width: 100%"
          >
            <el-option
              v-for="t in ACCOUNT_TYPES"
              :key="t.value"
              :label="t.label"
              :value="t.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="AppID" prop="app_id">
          <el-input v-model="editForm.app_id" placeholder="wx..." />
        </el-form-item>
        <el-form-item label="AppSecret" prop="app_secret">
          <el-input
            v-model="editForm.app_secret"
            type="password"
            show-password
            :placeholder="
              editMode === 'edit'
                ? '留空表示不修改'
                : editForm.account_type === 3
                  ? '模拟号可留空(走 MockChannel)'
                  : '请输入 AppSecret'
            "
          />
          <div v-if="editForm.account_type === 3" class="form-hint">
            测试/模拟号无需真实密钥,发文走本地 MockChannel 模拟,可零风险跑通全流程。
          </div>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="editForm.remark" type="textarea" :rows="2" placeholder="备注(可选)" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submitEdit">确定</el-button>
      </template>
    </el-dialog>

    <!-- 校验结果 -->
    <el-dialog v-model="verifyVisible" title="凭据校验结果" width="460px">
      <el-result
        v-if="verifyResult"
        :icon="verifyResult.ok === false ? 'error' : 'success'"
        :title="verifyResult.ok === false ? '校验未通过' : '校验通过'"
        :sub-title="`公众号: ${verifyMpName}`"
      >
        <template #extra>
          <el-descriptions :column="1" border size="small" class="verify-desc">
            <el-descriptions-item label="结果">
              <el-tag :type="verifyResult.ok === false ? 'danger' : 'success'" size="small">
                {{ verifyResult.ok === false ? '失败' : '成功' }}
              </el-tag>
            </el-descriptions-item>
            <el-descriptions-item v-if="verifyResult.checked" label="校验项">
              {{ verifyResult.checked }}
            </el-descriptions-item>
            <el-descriptions-item v-if="verifyResult.hint" label="说明">
              {{ verifyResult.hint }}
            </el-descriptions-item>
          </el-descriptions>
        </template>
      </el-result>
    </el-dialog>

    <!-- 分配运营 -->
    <el-dialog
      v-model="assignVisible"
      title="分配运营"
      width="820px"
      top="6vh"
    >
      <p class="dialog-sub">
        公众号: <b>{{ assignMp?.mp_name }}</b>
        <span class="muted">（全量覆盖：保存后以下列表即为最终运营名单）</span>
      </p>
      <div v-loading="assignLoading">
        <el-transfer
          v-model="assignedUserIds"
          :data="transferData"
          :titles="['可选用户', '已分配']"
          filterable
          filter-placeholder="搜索用户"
          @change="onTransferChange"
        />

        <el-divider content-position="left">权限级别设置</el-divider>
        <el-table :data="assignedDetails" border size="small" max-height="240">
          <el-table-column prop="name" label="运营人员" min-width="180" />
          <el-table-column label="权限级别" width="200">
            <template #default="{ row }">
              <el-select v-model="permMap[row.user_id]" size="small" style="width: 160px">
                <el-option
                  v-for="p in PERM_LEVELS"
                  :key="p.value"
                  :label="p.label"
                  :value="p.value"
                />
              </el-select>
            </template>
          </el-table-column>
        </el-table>
        <el-empty
          v-if="!assignedDetails.length"
          description="尚未分配任何运营"
          :image-size="60"
        />
      </div>
      <template #footer>
        <el-button @click="assignVisible = false">取消</el-button>
        <el-button type="primary" :loading="assignSaving" @click="submitAssign">
          保存分配
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
  font-weight: normal;
}
.dialog-sub {
  margin: 0 0 16px;
  color: #606266;
}
.form-hint {
  margin-top: 4px;
  font-size: 12px;
  line-height: 1.5;
  color: #909399;
}
.verify-desc {
  margin-top: 8px;
  text-align: left;
}
</style>
