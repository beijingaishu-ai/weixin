import { defineStore } from 'pinia'
import {
  getRefreshToken,
  registerTokenHandlers,
  setRefreshToken,
} from '@/api/http'
import { apiLogin, apiLogout, apiMe } from '@/api/modules'
import type { MeInfo, VisibleMp } from '@/api/types'

interface AuthState {
  accessToken: string | null // 内存
  userId: number | null
  username: string
  realName: string
  role: string
  roles: string[]
  perms: string[]
  visibleMp: VisibleMp[]
}

export const useAuthStore = defineStore('auth', {
  state: (): AuthState => ({
    accessToken: null,
    userId: null,
    username: '',
    realName: '',
    role: '',
    roles: [],
    perms: [],
    visibleMp: [],
  }),

  getters: {
    isLoggedIn: (state): boolean => !!state.accessToken || !!getRefreshToken(),
  },

  actions: {
    setAccessToken(token: string | null) {
      this.accessToken = token
    },

    hasPerm(code: string): boolean {
      if (!code) return true
      return this.perms.includes(code)
    },

    hasAnyPerm(codes: string[]): boolean {
      if (!codes.length) return true
      return codes.some((c) => this.perms.includes(c))
    },

    async login(username: string, password: string) {
      const data = await apiLogin(username, password)
      this.setAccessToken(data.access_token)
      setRefreshToken(data.refresh_token)
      // 登录返回的精简 user
      this.userId = data.user.id
      this.realName = data.user.real_name
      this.role = data.user.role
      this.perms = data.user.perms || []
      // 拉取完整信息 (roles / visible_mp 等)
      await this.loadMe()
    },

    async loadMe() {
      const me: MeInfo = await apiMe()
      this.userId = me.id
      this.username = me.username
      this.realName = me.real_name
      this.role = me.role
      this.roles = me.roles || []
      this.perms = me.perms || []
      this.visibleMp = me.visible_mp || []
      return me
    },

    async logout() {
      try {
        await apiLogout()
      } catch {
        // 忽略登出接口错误, 本地清理为准
      }
      this.clear()
    },

    clear() {
      this.accessToken = null
      this.userId = null
      this.username = ''
      this.realName = ''
      this.role = ''
      this.roles = []
      this.perms = []
      this.visibleMp = []
      setRefreshToken(null)
    },
  },
})

// 把 store 的 token 处理注册给 http 层 (打破循环依赖)
export function bindAuthToHttp() {
  const store = useAuthStore()
  registerTokenHandlers({
    getAccess: () => store.accessToken,
    setAccess: (t) => store.setAccessToken(t),
    onFail: () => {
      store.clear()
      // 跳登录由路由守卫/页面处理; 这里用 hash 兜底
      if (!location.hash.includes('/login')) {
        location.href = `${location.origin}${location.pathname}#/login`
      }
    },
  })
}
