/**
 * 用户相关接口封装
 * ================
 * 小白理解:把"和后端打交道的细节"包成一个个好记的方法名,
 * 页面里只写 authApi.login(...),不用关心网址、参数格式这些琐事。
 */
import { api } from './client'
import type { User } from '../stores/authStore'

/** 登录/注册成功后后端返回的数据 */
export interface LoginResult {
  access_token: string
  token_type: string
  user: User
}

export const authApi = {
  /** 登录:验证用户名密码,成功后拿到令牌 */
  login: (username: string, password: string) =>
    api.post<LoginResult>('/auth/login', { username, password }).then((r) => r.data),

  /** 注册:成功后自动登录(后端直接发令牌) */
  register: (username: string, password: string) =>
    api.post<LoginResult>('/auth/register', { username, password }).then((r) => r.data),

  /** 查询当前登录的是谁(刷新页面时用来确认身份) */
  me: () => api.get<User>('/auth/me').then((r) => r.data),

  /** 修改密码 */
  changePassword: (oldPassword: string, newPassword: string) =>
    api
      .post<{ message: string }>('/auth/change-password', {
        old_password: oldPassword,
        new_password: newPassword,
      })
      .then((r) => r.data),
}
