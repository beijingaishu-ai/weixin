import axios, {
  type AxiosInstance,
  type AxiosRequestConfig,
  type AxiosResponse,
  type InternalAxiosRequestConfig,
} from 'axios'
import { ElMessage } from 'element-plus'
import type { ApiResult } from './types'

const BASE_URL = '/api/v1'
const REFRESH_KEY = 'weixin_refresh_token'

// -------- refresh_token 持久化 (localStorage) --------
export function getRefreshToken(): string | null {
  return localStorage.getItem(REFRESH_KEY)
}
export function setRefreshToken(token: string | null) {
  if (token) localStorage.setItem(REFRESH_KEY, token)
  else localStorage.removeItem(REFRESH_KEY)
}

// access_token 存内存, 由 auth store 注入 (避免循环依赖用回调)
let accessTokenGetter: () => string | null = () => null
let accessTokenSetter: (t: string | null) => void = () => {}
let onAuthFailed: () => void = () => {}

export function registerTokenHandlers(handlers: {
  getAccess: () => string | null
  setAccess: (t: string | null) => void
  onFail: () => void
}) {
  accessTokenGetter = handlers.getAccess
  accessTokenSetter = handlers.setAccess
  onAuthFailed = handlers.onFail
}

// 内部 axios 实例
const service: AxiosInstance = axios.create({
  baseURL: BASE_URL,
  timeout: 20000,
})

// 请求拦截: 注入 Authorization
service.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    const token = accessTokenGetter()
    if (token && config.headers) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => Promise.reject(error),
)

// -------- refresh 并发控制 --------
let isRefreshing = false
let pendingQueue: Array<(token: string | null) => void> = []

function flushQueue(token: string | null) {
  pendingQueue.forEach((cb) => cb(token))
  pendingQueue = []
}

// 用 refresh_token 换新的 access_token
async function doRefresh(): Promise<string | null> {
  const refresh = getRefreshToken()
  if (!refresh) return null
  try {
    // 直接用裸 axios, 避免走拦截器
    const resp = await axios.post<ApiResult<{ access_token: string; refresh_token?: string }>>(
      `${BASE_URL}/auth/refresh`,
      { refresh_token: refresh },
    )
    const body = resp.data
    if (body.code !== 0 || !body.data?.access_token) return null
    accessTokenSetter(body.data.access_token)
    if (body.data.refresh_token) setRefreshToken(body.data.refresh_token)
    return body.data.access_token
  } catch {
    return null
  }
}

interface RetriableConfig extends InternalAxiosRequestConfig {
  _retried?: boolean
}

// 响应拦截: 解包 data; code!=0 报错; 401 续期重放
service.interceptors.response.use(
  (response: AxiosResponse<ApiResult>) => {
    const body = response.data
    // 非标准包装 (如二进制) 直接返回
    if (body == null || typeof body !== 'object' || !('code' in body)) {
      return response.data as unknown as never
    }
    if (body.code !== 0) {
      ElMessage.error(body.message || '请求失败')
      return Promise.reject(new Error(body.message || `业务错误 code=${body.code}`))
    }
    // 解包: 直接把 data 作为 resolve 值
    return body.data as never
  },
  async (error) => {
    const config = error.config as RetriableConfig | undefined
    const status = error.response?.status
    const url: string = config?.url || ''
    const isRefreshCall = url.includes('/auth/refresh')

    // HTTP 401 且非 refresh 请求且未重放过 -> 尝试续期
    if (status === 401 && config && !isRefreshCall && !config._retried) {
      config._retried = true

      if (isRefreshing) {
        // 已有刷新在进行, 排队等待
        return new Promise((resolve, reject) => {
          pendingQueue.push((token) => {
            if (token) {
              if (config.headers) config.headers.Authorization = `Bearer ${token}`
              resolve(service(config))
            } else {
              reject(error)
            }
          })
        })
      }

      isRefreshing = true
      const newToken = await doRefresh()
      isRefreshing = false
      flushQueue(newToken)

      if (newToken) {
        if (config.headers) config.headers.Authorization = `Bearer ${newToken}`
        return service(config) // 重放一次
      }
      // 续期失败 -> 登出跳登录
      onAuthFailed()
      ElMessage.error('登录已过期, 请重新登录')
      return Promise.reject(error)
    }

    // 其它 HTTP 错误
    if (status && !isRefreshCall) {
      const msg =
        (error.response?.data as ApiResult | undefined)?.message ||
        error.message ||
        `请求错误 (${status})`
      ElMessage.error(msg)
    }
    return Promise.reject(error)
  },
)

// -------- 类型化封装: 拦截器已解包 data, 故返回 T --------
export function httpGet<T = unknown>(url: string, config?: AxiosRequestConfig): Promise<T> {
  return service.get(url, config) as unknown as Promise<T>
}
export function httpPost<T = unknown>(
  url: string,
  data?: unknown,
  config?: AxiosRequestConfig,
): Promise<T> {
  return service.post(url, data, config) as unknown as Promise<T>
}
export function httpPut<T = unknown>(
  url: string,
  data?: unknown,
  config?: AxiosRequestConfig,
): Promise<T> {
  return service.put(url, data, config) as unknown as Promise<T>
}
export function httpPatch<T = unknown>(
  url: string,
  data?: unknown,
  config?: AxiosRequestConfig,
): Promise<T> {
  return service.patch(url, data, config) as unknown as Promise<T>
}
export function httpDelete<T = unknown>(url: string, config?: AxiosRequestConfig): Promise<T> {
  return service.delete(url, config) as unknown as Promise<T>
}

export default service
