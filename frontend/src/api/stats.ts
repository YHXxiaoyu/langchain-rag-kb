/**
 * 管理员统计接口封装
 * ==================
 */
import { api } from './client'

/** 平台全景统计数据 */
export interface AdminStats {
  users: { total: number; admins: number }
  conversations: { total: number }
  messages: {
    total: number
    questions: number
    likes: number
    dislikes: number
    like_rate: number
  }
  tokens: { total: number }
  knowledge: { documents: number; chunks: number }
  daily_trend: { date: string; count: number }[]
  cache: { size: number; hits: number; misses: number; hit_rate: number }
}

export const statsApi = {
  get: () => api.get<AdminStats>('/admin/stats').then((r) => r.data),
}
