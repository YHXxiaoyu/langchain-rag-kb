/**
 * 主界面框架(登录之后看到的整体布局)
 * ==================================
 * 布局说明:
 *   ┌──────────┬────────────────────────────┐
 *   │  左导航   │  顶部条(用户菜单)          │
 *   │ 智能问答  ├────────────────────────────┤
 *   │ 知识库管理│                            │
 *   │ (仅管理员)│      页面内容区域           │
 *   │  用户信息 │                            │
 *   └──────────┴────────────────────────────┘
 *
 * 权限体现:普通用户的左侧菜单里根本没有"知识库管理"这一项
 */
import { useEffect, useState } from 'react'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { App, Avatar, Button, Dropdown, Layout, Menu, Space, Tag, Tooltip, Typography } from 'antd'
import {
  DashboardOutlined,
  DatabaseOutlined,
  KeyOutlined,
  LogoutOutlined,
  MessageOutlined,
  MoonOutlined,
  SunOutlined,
  UserOutlined,
} from '@ant-design/icons'
import { authApi } from '../api/auth'
import { isAdmin, useAuthStore } from '../stores/authStore'
import { useThemeStore } from '../stores/themeStore'
import ChangePasswordModal from '../components/ChangePasswordModal'

const { Sider, Header, Content } = Layout
const { Text } = Typography

export default function MainLayout() {
  const { modal, message } = App.useApp()
  const navigate = useNavigate()
  const location = useLocation()
  const user = useAuthStore((s) => s.user)
  const logout = useAuthStore((s) => s.logout)
  const updateUser = useAuthStore((s) => s.updateUser)
  const dark = useThemeStore((s) => s.dark)
  const toggleTheme = useThemeStore((s) => s.toggle)

  const [pwdOpen, setPwdOpen] = useState(false) // 修改密码弹窗开关

  // 页面打开/刷新时,跟后端确认一次"令牌还有效吗",顺便同步最新的用户信息。
  // 若令牌已过期:axios 拦截器会自动清空登录状态,路由守卫随后把用户送回登录页。
  useEffect(() => {
    authApi
      .me()
      .then((fresh) => updateUser(fresh))
      .catch(() => {
        /* 失败处理已由拦截器统一完成,这里无需额外操作 */
      })
  }, [updateUser])

  const admin = isAdmin(user)

  // 左侧菜单项(管理员才多出"知识库管理"和"数据看板")
  const menuItems = [
    { key: '/chat', icon: <MessageOutlined />, label: '智能问答' },
    ...(admin
      ? [
          { key: '/knowledge', icon: <DatabaseOutlined />, label: '知识库管理' },
          { key: '/dashboard', icon: <DashboardOutlined />, label: '数据看板' },
        ]
      : []),
  ]

  // 顶部标题随页面变化
  const pageTitle =
    location.pathname === '/knowledge'
      ? '知识库管理'
      : location.pathname === '/dashboard'
        ? '数据看板'
        : '智能问答'

  // 右上角用户菜单项
  const userMenuItems = [
    { key: 'change-password', icon: <KeyOutlined />, label: '修改密码' },
    { type: 'divider' as const },
    { key: 'logout', icon: <LogoutOutlined />, label: '退出登录', danger: true },
  ]

  /** 处理右上角菜单点击 */
  const onUserMenuClick = ({ key }: { key: string }) => {
    if (key === 'change-password') {
      setPwdOpen(true)
    } else if (key === 'logout') {
      modal.confirm({
        title: '确认退出登录?',
        content: '退出后需要重新输入用户名和密码',
        okText: '退出',
        cancelText: '取消',
        onOk: () => {
          logout()
          message.success('已退出登录')
          navigate('/login', { replace: true })
        },
      })
    }
  }

  return (
    <Layout style={{ minHeight: '100vh' }}>
      {/* ---------- 左侧导航栏 ---------- */}
      <Sider width={216} style={{ background: 'var(--bg-chat)', borderRight: '1px solid var(--border-soft)' }}>
        <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
          {/* 顶部 Logo */}
          <div style={{ padding: '20px 20px 16px', display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ fontSize: 26 }}>🐟</span>
            <div>
              <div style={{ fontSize: 15, fontWeight: 600, lineHeight: 1.2 }}>小鱼知识库</div>
              <div style={{ fontSize: 11, color: '#999' }}>智能问答系统</div>
            </div>
          </div>

          {/* 菜单 */}
          <Menu
            mode="inline"
            selectedKeys={[location.pathname]}
            items={menuItems}
            onClick={({ key }) => navigate(key)}
            style={{ borderInlineEnd: 'none', flex: 1 }}
          />

          {/* 底部用户信息卡片 */}
          <div style={{ padding: 16, borderTop: '1px solid var(--border-soft)' }}>
            <Space>
              <Avatar size={32} style={{ background: admin ? '#faad14' : '#1677ff' }} icon={<UserOutlined />} />
              <div>
                <div style={{ fontSize: 13, fontWeight: 500 }}>{user?.username}</div>
                <Text type="secondary" style={{ fontSize: 11 }}>
                  {admin ? '管理员' : '普通用户'}
                </Text>
              </div>
            </Space>
          </div>
        </div>
      </Sider>

      <Layout>
        {/* ---------- 顶部条 ---------- */}
        <Header
          style={{
            background: 'var(--bg-chat)',
            padding: '0 24px',
            borderBottom: '1px solid var(--border-soft)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            height: 56,
            lineHeight: '56px',
          }}
        >
          <Text strong style={{ fontSize: 15 }}>
            {pageTitle}
          </Text>

          <Space size={4}>
            {/* 深色 / 浅色主题切换 */}
            <Tooltip title={dark ? '切换到浅色模式' : '切换到深色模式'}>
              <Button
                type="text"
                icon={dark ? <SunOutlined /> : <MoonOutlined />}
                onClick={toggleTheme}
              />
            </Tooltip>

            <Dropdown menu={{ items: userMenuItems, onClick: onUserMenuClick }} placement="bottomRight">
              <Space style={{ cursor: 'pointer' }}>
                <Avatar size={28} style={{ background: admin ? '#faad14' : '#1677ff' }} icon={<UserOutlined />} />
                <Text>{user?.username}</Text>
                {admin && <Tag color="gold" style={{ marginInlineEnd: 0 }}>管理员</Tag>}
              </Space>
            </Dropdown>
          </Space>
        </Header>

        {/* ---------- 页面内容区 ---------- */}
        <Content style={{ background: 'var(--bg-page)', overflow: 'auto' }}>
          <Outlet />
        </Content>
      </Layout>

      {/* 修改密码弹窗 */}
      <ChangePasswordModal open={pwdOpen} onClose={() => setPwdOpen(false)} />
    </Layout>
  )
}
