<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessageBox, ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

interface MenuItem {
  index: string
  title: string
  icon: string
  perm?: string
}
interface MenuGroup {
  group: true
  index: string
  title: string
  icon: string
  children: MenuItem[]
}
type MenuNode = MenuItem | MenuGroup

function isGroup(m: MenuNode): m is MenuGroup {
  return (m as MenuGroup).group === true
}

const allMenus: MenuNode[] = [
  { index: '/dashboard', title: '工作台', icon: 'HomeFilled' },
  { index: '/users', title: '用户管理', icon: 'User', perm: 'user:manage' },
  { index: '/mp-accounts', title: '公众号台账', icon: 'Promotion', perm: 'mp:account:view' },
  {
    group: true,
    index: 'grp-content',
    title: '内容中心',
    icon: 'Collection',
    children: [
      { index: '/materials', title: '素材库', icon: 'PictureFilled', perm: 'content:material:view' },
      { index: '/articles', title: '图文管理', icon: 'Tickets', perm: 'content:article:view' },
      { index: '/review-queue', title: '审核队列', icon: 'Finished', perm: 'content:article:audit' },
    ],
  },
  {
    group: true,
    index: 'grp-publish',
    title: '发布管理',
    icon: 'Position',
    children: [
      { index: '/publish-tasks', title: '发布任务', icon: 'Promotion', perm: 'publish:task:view' },
    ],
  },
  {
    group: true,
    index: 'grp-collect',
    title: '采集中心',
    icon: 'Connection',
    children: [
      { index: '/collect-sources', title: '采集源', icon: 'Connection', perm: 'collect:source:view' },
      { index: '/collect-articles', title: '采集文章', icon: 'Files', perm: 'collect:article:view' },
    ],
  },
  {
    group: true,
    index: 'grp-mapping',
    title: '映射规则',
    icon: 'Share',
    children: [
      { index: '/mapping-rules', title: '映射规则', icon: 'Share', perm: 'mapping:rule:view' },
    ],
  },
  { index: '/audit', title: '审计日志', icon: 'Document', perm: 'user:manage' },
]

// 按 perms 过滤菜单; 分组内子项全部无权限则隐藏整个分组
const menus = computed<MenuNode[]>(() =>
  allMenus
    .map((m) => {
      if (isGroup(m)) {
        const children = m.children.filter((c) => !c.perm || auth.hasPerm(c.perm))
        return children.length ? { ...m, children } : null
      }
      return !m.perm || auth.hasPerm(m.perm) ? m : null
    })
    .filter((m): m is MenuNode => m !== null),
)

const activeMenu = computed(() => {
  // 图文编辑子路由高亮「图文管理」
  if (route.path.startsWith('/articles/')) return '/articles'
  return route.path
})

async function handleLogout() {
  try {
    await ElMessageBox.confirm('确定要退出登录吗?', '提示', {
      type: 'warning',
      confirmButtonText: '退出',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  await auth.logout()
  ElMessage.success('已退出登录')
  router.replace('/login')
}
</script>

<template>
  <el-container class="layout-root">
    <el-aside width="220px" class="layout-aside">
      <div class="logo">
        <el-icon><Platform /></el-icon>
        <span class="logo-text">M1 管理后台</span>
      </div>
      <el-menu
        :default-active="activeMenu"
        router
        class="layout-menu"
        background-color="#1f2d3d"
        text-color="#c0c4cc"
        active-text-color="#409eff"
      >
        <template v-for="m in menus" :key="m.index">
          <el-sub-menu v-if="isGroup(m)" :index="m.index">
            <template #title>
              <el-icon><component :is="m.icon" /></el-icon>
              <span>{{ m.title }}</span>
            </template>
            <el-menu-item v-for="c in m.children" :key="c.index" :index="c.index">
              <el-icon><component :is="c.icon" /></el-icon>
              <span>{{ c.title }}</span>
            </el-menu-item>
          </el-sub-menu>
          <el-menu-item v-else :index="m.index">
            <el-icon><component :is="m.icon" /></el-icon>
            <span>{{ m.title }}</span>
          </el-menu-item>
        </template>
      </el-menu>
    </el-aside>

    <el-container>
      <el-header class="layout-header">
        <div class="header-left"></div>
        <div class="header-right">
          <el-dropdown trigger="click">
            <span class="user-badge">
              <el-avatar :size="30" class="user-avatar">
                {{ (auth.realName || auth.username || '?').slice(0, 1) }}
              </el-avatar>
              <span class="user-name">{{ auth.realName || auth.username }}</span>
              <el-tag size="small" type="info" class="role-tag">{{ auth.role || '-' }}</el-tag>
              <el-icon><ArrowDown /></el-icon>
            </span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item disabled>
                  {{ auth.username }}
                </el-dropdown-item>
                <el-dropdown-item divided @click="handleLogout">
                  <el-icon><SwitchButton /></el-icon>
                  退出登录
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </el-header>

      <el-main class="layout-main">
        <router-view v-slot="{ Component }">
          <transition name="fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </el-main>
    </el-container>
  </el-container>
</template>

<style scoped>
.layout-root {
  height: 100%;
}

.layout-aside {
  background-color: #1f2d3d;
  overflow-x: hidden;
}

.logo {
  height: 60px;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 18px;
  color: #fff;
  font-size: 17px;
  font-weight: 600;
  background-color: #182430;
}
.logo-text {
  white-space: nowrap;
}

.layout-menu {
  border-right: none;
}

.layout-header {
  height: 60px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  background-color: #fff;
  border-bottom: 1px solid #ebeef5;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.04);
}

.header-right {
  display: flex;
  align-items: center;
}

.user-badge {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  outline: none;
}
.user-avatar {
  background-color: #409eff;
  color: #fff;
}
.user-name {
  font-size: 14px;
  color: #303133;
}
.role-tag {
  margin-left: 2px;
}

.layout-main {
  background-color: #f0f2f5;
  padding: 0;
  overflow-y: auto;
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.15s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
