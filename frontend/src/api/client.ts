/**
 * HTTP 请求客户端(前后端通信的"快递员")
 * ======================================
 * 小白理解:前端要跟后端说话(登录、提问、传文件),都靠这个"快递员"跑腿。
 * 它有两个自动功能,省得每个页面都写一遍:
 *
 *   1. 出发前自动贴上"通行证"(登录令牌),后端一看就知道你是谁
 *   2. 回来后自动检查:如果后端说"没登录/过期了"(401),自动退回登录页
 */
import axios from 'axios'
import { useAuthStore } from '../stores/authStore'

export const api = axios.create({
  baseURL: '/api', // 所有请求都以 /api 开头(开发时由 Vite 自动转给后端)
  timeout: 120000, // 最长等 2 分钟(AI 回答较慢时要耐心等)
})

// ---------- 出发前:自动贴上通行证 ----------
api.interceptors.request.use((config) => {
  const token = useAuthStore.getState().token
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// ---------- 回来后:统一处理"登录过期" ----------
api.interceptors.response.use(
  (response) => response,
  (error) => {
    const status = error.response?.status
    // 401 = 未登录或令牌过期。清掉本地状态,页面会自动跳回登录页
    if (status === 401) {
      const { token, logout } = useAuthStore.getState()
      // 只有"本来已登录"才需要跳转(登录页输错密码不该被踢来踢去)
      if (token) logout()
    }
    return Promise.reject(error)
  },
)

/** 从各种异常里提取一句给用户看的提示语(后端的中文提示优先) */
export function getErrorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail
    if (typeof detail === 'string') return detail
    // 表单校验错误(422):后端会返回一个数组,取第一条的说明
    if (Array.isArray(detail) && detail.length > 0) {
      return detail[0]?.msg ?? '填写的内容不符合要求'
    }
    if (error.code === 'ECONNABORTED') return '请求超时,请稍后重试'
    if (!error.response) return '无法连接后端服务,请确认后端已启动'
  }
  return '操作失败,请稍后重试'
}
