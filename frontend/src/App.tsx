/**
 * 路由配置(页面的"交通指挥图")
 * ============================
 * 小白理解:用户访问不同网址,该显示哪个页面、要不要先登录、有没有权限,
 * 全部在这里规定。两道关卡:

 *   RequireAuth  —— 未登录的访客,一律送回登录页
 *   RequireAdmin —— 登录了但不是管理员,知识库管理页进不去(送回问答页)
 */
import type { ReactNode } from 'react'
import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import LoginPage from './pages/Login'
import MainLayout from './layouts/MainLayout'
import ChatPage from './pages/Chat'
import KnowledgePage from './pages/Knowledge'
import DashboardPage from './pages/Dashboard'
import { isAdmin, useAuthStore } from './stores/authStore'

/** 关卡一:必须登录才能通过 */
function RequireAuth({ children }: { children: ReactNode }) {
  const token = useAuthStore((s) => s.token)
  const location = useLocation()

  if (!token) {
    // 记下用户原本想去的页面,登录成功后自动送回去
    return <Navigate to="/login" state={{ from: location }} replace />
  }
  return <>{children}</>
}

/** 关卡二:必须是管理员才能通过 */
function RequireAdmin({ children }: { children: ReactNode }) {
  const user = useAuthStore((s) => s.user)

  if (!isAdmin(user)) {
    // 普通用户即使手敲网址也进不来,直接送回问答页
    return <Navigate to="/chat" replace />
  }
  return <>{children}</>
}

/** 已登录的用户访问登录页时,直接送进问答页(不用重复登录) */
function RedirectIfLoggedIn({ children }: { children: ReactNode }) {
  const token = useAuthStore((s) => s.token)
  if (token) return <Navigate to="/chat" replace />
  return <>{children}</>
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        {/* 登录/注册页 */}
        <Route
          path="/login"
          element={
            <RedirectIfLoggedIn>
              <LoginPage />
            </RedirectIfLoggedIn>
          }
        />

        {/* 登录后才能访问的主界面 */}
        <Route
          element={
            <RequireAuth>
              <MainLayout />
            </RequireAuth>
          }
        >
          <Route path="/chat" element={<ChatPage />} />
          {/* 知识库管理:再加一道管理员关卡 */}
          <Route
            path="/knowledge"
            element={
              <RequireAdmin>
                <KnowledgePage />
              </RequireAdmin>
            }
          />
          {/* 数据看板:同样只有管理员能看 */}
          <Route
            path="/dashboard"
            element={
              <RequireAdmin>
                <DashboardPage />
              </RequireAdmin>
            }
          />
        </Route>

        {/* 其他任何网址:统一送回问答页 */}
        <Route path="*" element={<Navigate to="/chat" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
