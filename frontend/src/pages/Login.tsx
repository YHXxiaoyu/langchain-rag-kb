/**
 * 登录 / 注册页
 * ============
 * 小白理解:整个系统的"大门"。左边是门面介绍,右边是登录或注册的表单,
 * 两个表单用上方的标签页切换。
 */
import { useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { App, Button, Card, Form, Input, Tabs, Typography } from 'antd'
import { LockOutlined, UserOutlined, RobotOutlined, FileSearchOutlined, MessageOutlined, SafetyOutlined } from '@ant-design/icons'
import { authApi } from '../api/auth'
import { getErrorMessage } from '../api/client'
import { useAuthStore } from '../stores/authStore'

const { Title, Text, Paragraph } = Typography

/** 表单字段类型 */
interface FormValues {
  username: string
  password: string
  confirm?: string
}

export default function LoginPage() {
  const { message } = App.useApp()
  const navigate = useNavigate()
  const location = useLocation()
  const setAuth = useAuthStore((s) => s.setAuth)

  const [tab, setTab] = useState('login') // 当前显示:login=登录,register=注册
  const [loading, setLoading] = useState(false) // 请求进行中(按钮转圈,防止重复点击)

  // 登录成功/注册成功后,跳回"来时想去的页面"(默认去问答页)
  const from = (location.state as { from?: { pathname: string } })?.from?.pathname ?? '/chat'

  /** 处理登录 */
  const handleLogin = async (values: FormValues) => {
    setLoading(true)
    try {
      const data = await authApi.login(values.username, values.password)
      setAuth(data.access_token, data.user)
      message.success(`欢迎回来,${data.user.username}!`)
      navigate(from, { replace: true })
    } catch (err) {
      message.error(getErrorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  /** 处理注册(注册成功后端会直接发令牌,即自动登录) */
  const handleRegister = async (values: FormValues) => {
    setLoading(true)
    try {
      const data = await authApi.register(values.username, values.password)
      setAuth(data.access_token, data.user)
      message.success('注册成功,已自动登录')
      navigate('/chat', { replace: true })
    } catch (err) {
      message.error(getErrorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div
      className="login-page"
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 24,
      }}
    >
      <Card
        style={{ width: 880, overflow: 'hidden', boxShadow: '0 8px 40px rgba(0,0,0,0.08)' }}
        styles={{ body: { padding: 0, display: 'flex', minHeight: 480 } }}
      >
        {/* ---------- 左侧:品牌介绍区 ---------- */}
        <div
          style={{
            width: 380,
            padding: '48px 36px',
            background: 'linear-gradient(160deg, #1677ff 0%, #0958d9 100%)',
            color: '#fff',
            display: 'flex',
            flexDirection: 'column',
            justifyContent: 'center',
          }}
        >
          <RobotOutlined style={{ fontSize: 48, marginBottom: 20 }} />
          <Title level={3} style={{ color: '#fff', marginBottom: 8 }}>
            小鱼知识库问答系统
          </Title>
          <Paragraph style={{ color: 'rgba(255,255,255,0.85)', marginBottom: 32 }}>
            基于 LangChain 的电商商品知识库 RAG 问答系统
          </Paragraph>

          {/* 三个卖点 */}
          {[
            { icon: <FileSearchOutlined />, text: '知识库驱动的精准回答' },
            { icon: <MessageOutlined />, text: '回答标注引用来源,有据可查' },
            { icon: <SafetyOutlined />, text: '多用户隔离,数据安全' },
          ].map((item) => (
            <div key={item.text} style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14 }}>
              <span style={{ fontSize: 16, opacity: 0.9 }}>{item.icon}</span>
              <Text style={{ color: 'rgba(255,255,255,0.92)' }}>{item.text}</Text>
            </div>
          ))}
        </div>

        {/* ---------- 右侧:表单区 ---------- */}
        <div style={{ flex: 1, padding: '40px 44px', display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
          <Tabs
            activeKey={tab}
            onChange={setTab}
            centered
            items={[
              {
                key: 'login',
                label: '登录',
                children: (
                  <Form<FormValues> layout="vertical" onFinish={handleLogin} size="large" requiredMark={false}>
                    <Form.Item
                      name="username"
                      label="用户名"
                      rules={[{ required: true, message: '请输入用户名' }]}
                    >
                      <Input prefix={<UserOutlined />} placeholder="请输入用户名" autoComplete="username" />
                    </Form.Item>
                    <Form.Item
                      name="password"
                      label="密码"
                      rules={[{ required: true, message: '请输入密码' }]}
                    >
                      <Input.Password prefix={<LockOutlined />} placeholder="请输入密码" autoComplete="current-password" />
                    </Form.Item>
                    <Form.Item style={{ marginBottom: 0, marginTop: 8 }}>
                      <Button type="primary" htmlType="submit" block loading={loading}>
                        登 录
                      </Button>
                    </Form.Item>
                  </Form>
                ),
              },
              {
                key: 'register',
                label: '注册',
                children: (
                  <Form<FormValues> layout="vertical" onFinish={handleRegister} size="large" requiredMark={false}>
                    <Form.Item
                      name="username"
                      label="用户名"
                      rules={[
                        { required: true, message: '请输入用户名' },
                        { min: 3, max: 20, message: '用户名需 3~20 个字符' },
                        { pattern: /^\S+$/, message: '用户名不能包含空格' },
                      ]}
                    >
                      <Input prefix={<UserOutlined />} placeholder="3~20 个字符,不能有空格" autoComplete="username" />
                    </Form.Item>
                    <Form.Item
                      name="password"
                      label="密码"
                      rules={[
                        { required: true, message: '请输入密码' },
                        { min: 6, message: '密码至少 6 位' },
                      ]}
                    >
                      <Input.Password prefix={<LockOutlined />} placeholder="至少 6 位" autoComplete="new-password" />
                    </Form.Item>
                    <Form.Item
                      name="confirm"
                      label="确认密码"
                      dependencies={['password']}
                      rules={[
                        { required: true, message: '请再输入一次密码' },
                        // 自定义校验:两次输入的密码必须一致
                        ({ getFieldValue }) => ({
                          validator(_, value) {
                            if (!value || getFieldValue('password') === value) return Promise.resolve()
                            return Promise.reject(new Error('两次输入的密码不一致'))
                          },
                        }),
                      ]}
                    >
                      <Input.Password prefix={<LockOutlined />} placeholder="再输入一次密码" autoComplete="new-password" />
                    </Form.Item>
                    <Form.Item style={{ marginBottom: 0, marginTop: 8 }}>
                      <Button type="primary" htmlType="submit" block loading={loading}>
                        注 册
                      </Button>
                    </Form.Item>
                  </Form>
                ),
              },
            ]}
          />

          {/* 演示账号提示(方便快速登录体验) */}
          <Text type="secondary" style={{ display: 'block', textAlign: 'center', marginTop: 20, fontSize: 12 }}>
            管理员演示账号:admin / 123456
          </Text>
        </div>
      </Card>
    </div>
  )
}
