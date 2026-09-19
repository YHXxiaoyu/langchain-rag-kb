/**
 * 登录状态管理(一个"全局记忆盒")
 * ==============================
 * 小白理解:浏览器里需要一个地方记住"当前是谁登录了"。
 * 这个文件就是那个记忆盒:存令牌和用户信息,并把它同步保存到浏览器本地,
 * 这样刷新页面、关掉重开,登录状态都还在。
 *
 * 技术上用的是 zustand(轻量状态管理库),persist 中间件负责自动存/取本地存储。
 */
import { create } from 'zustand'
import { persist } from 'zustand/middleware'

/** 用户信息(和後端 /api/auth/me 返回的结构一致) */
export interface User {
  id: number
  username: string
  role: string // admin = 管理员, user = 普通用户
  created_at: string
}

interface AuthState {
  token: string | null // 登录令牌
  user: User | null    // 当前用户
  /** 登录/注册成功后调用:把令牌和用户信息一起存进记忆盒 */
  setAuth: (token: string, user: User) => void
  /** 刷新用户信息(令牌不变,只更新资料,如角色变化) */
  updateUser: (user: User) => void
  /** 退出登录:清空记忆盒 */
  logout: () => void
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      token: null,
      user: null,
      setAuth: (token, user) => set({ token, user }),
      updateUser: (user) => set({ user }),
      logout: () => set({ token: null, user: null }),
    }),
    {
      name: 'xiaoyu-rag-auth', // 存在浏览器本地存储里的键名
    },
  ),
)

/** 便捷判断:当前用户是不是管理员(组件里直接调用) */
export function isAdmin(user: User | null): boolean {
  return user?.role === 'admin'
}
