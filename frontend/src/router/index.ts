import { createRouter, createWebHashHistory, type RouteRecordRaw } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/Login.vue'),
    meta: { public: true, title: '登录' },
  },
  {
    path: '/',
    component: () => import('@/layouts/MainLayout.vue'),
    redirect: '/dashboard',
    children: [
      {
        path: 'dashboard',
        name: 'dashboard',
        component: () => import('@/views/Dashboard.vue'),
        meta: { title: '工作台', icon: 'HomeFilled' },
      },
      {
        path: 'users',
        name: 'users',
        component: () => import('@/views/Users.vue'),
        meta: { title: '用户管理', icon: 'User', perm: 'user:manage' },
      },
      {
        path: 'mp-accounts',
        name: 'mp-accounts',
        component: () => import('@/views/MpAccounts.vue'),
        meta: { title: '公众号台账', icon: 'Promotion', perm: 'mp:account:view' },
      },
      {
        path: 'materials',
        name: 'materials',
        component: () => import('@/views/Materials.vue'),
        meta: { title: '素材库', icon: 'PictureFilled', perm: 'content:material:view' },
      },
      {
        path: 'articles',
        name: 'articles',
        component: () => import('@/views/Articles.vue'),
        meta: { title: '图文管理', icon: 'Tickets', perm: 'content:article:view' },
      },
      {
        path: 'review-queue',
        name: 'review-queue',
        component: () => import('@/views/ReviewQueue.vue'),
        meta: { title: '审核队列', icon: 'Finished', perm: 'content:article:audit' },
      },
      {
        path: 'articles/new',
        name: 'article-new',
        component: () => import('@/views/ArticleEditor.vue'),
        meta: { title: '新建图文', perm: 'content:article:edit', hidden: true },
      },
      {
        path: 'articles/:id/edit',
        name: 'article-edit',
        component: () => import('@/views/ArticleEditor.vue'),
        meta: { title: '编辑图文', perm: 'content:article:edit', hidden: true },
      },
      {
        path: 'publish-tasks',
        name: 'publish-tasks',
        component: () => import('@/views/PublishTasks.vue'),
        meta: { title: '发布任务', icon: 'Promotion', perm: 'publish:task:view' },
      },
      {
        path: 'collect-sources',
        name: 'collect-sources',
        component: () => import('@/views/CollectSources.vue'),
        meta: { title: '采集源', icon: 'Connection', perm: 'collect:source:view' },
      },
      {
        path: 'collect-articles',
        name: 'collect-articles',
        component: () => import('@/views/CollectArticles.vue'),
        meta: { title: '采集文章', icon: 'Files', perm: 'collect:article:view' },
      },
      {
        path: 'mapping-rules',
        name: 'mapping-rules',
        component: () => import('@/views/MappingRules.vue'),
        meta: { title: '映射规则', icon: 'Share', perm: 'mapping:rule:view' },
      },
      {
        path: 'audit',
        name: 'audit',
        component: () => import('@/views/Audit.vue'),
        meta: { title: '审计日志', icon: 'Document', perm: 'user:manage' },
      },
    ],
  },
  {
    path: '/:pathMatch(.*)*',
    redirect: '/dashboard',
  },
]

const router = createRouter({
  history: createWebHashHistory(),
  routes,
})

// 全局前置守卫
router.beforeEach(async (to) => {
  const auth = useAuthStore()

  // 公开页
  if (to.meta.public) {
    return true
  }

  // 未登录 -> /login
  if (!auth.isLoggedIn) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }

  // 已有 refresh 但内存无 user (刷新页面) -> 尝试恢复
  if (!auth.userId) {
    try {
      await auth.loadMe()
    } catch {
      auth.clear()
      return { path: '/login', query: { redirect: to.fullPath } }
    }
  }

  // 权限校验
  const perm = to.meta.perm as string | undefined
  if (perm && !auth.hasPerm(perm)) {
    return { path: '/dashboard' }
  }

  return true
})

router.afterEach((to) => {
  const title = (to.meta.title as string) || ''
  document.title = title ? `${title} - M1 管理后台` : 'M1 管理后台'
})

export default router
