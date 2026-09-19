/**
 * 修改密码弹窗
 * ============
 * 小白理解:点右上角头像 → "修改密码",弹出的这个小窗口。
 * 改完密码后需要重新登录(相当于换了一把新钥匙,旧钥匙作废)。
 */
import { useState } from 'react'
import { App, Form, Input, Modal } from 'antd'
import { LockOutlined } from '@ant-design/icons'
import { authApi } from '../api/auth'
import { getErrorMessage } from '../api/client'
import { useAuthStore } from '../stores/authStore'

interface Props {
  open: boolean                                  // 弹窗是否显示
  onClose: () => void                            // 关闭弹窗的回调
}

interface FormValues {
  old_password: string
  new_password: string
  confirm: string
}

export default function ChangePasswordModal({ open, onClose }: Props) {
  const { message } = App.useApp()
  const [form] = Form.useForm<FormValues>()
  const [loading, setLoading] = useState(false)
  const logout = useAuthStore((s) => s.logout)

  /** 提交修改 */
  const handleOk = async () => {
    const values = await form.validateFields()
    setLoading(true)
    try {
      const res = await authApi.changePassword(values.old_password, values.new_password)
      message.success(res.message || '密码修改成功')
      form.resetFields()
      onClose()
      // 密码已变,令牌作废:自动退出登录,让用户用新密码重新登录
      logout()
    } catch (err) {
      message.error(getErrorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  return (
    <Modal
      title="修改密码"
      open={open}
      onOk={handleOk}
      onCancel={() => {
        form.resetFields()
        onClose()
      }}
      confirmLoading={loading}
      okText="确认修改"
      cancelText="取消"
      destroyOnHidden
    >
      <Form<FormValues> form={form} layout="vertical" style={{ marginTop: 16 }} requiredMark={false}>
        <Form.Item
          name="old_password"
          label="当前密码"
          rules={[{ required: true, message: '请输入当前密码' }]}
        >
          <Input.Password prefix={<LockOutlined />} placeholder="请输入当前密码" autoComplete="current-password" />
        </Form.Item>
        <Form.Item
          name="new_password"
          label="新密码"
          rules={[
            { required: true, message: '请输入新密码' },
            { min: 6, message: '新密码至少 6 位' },
          ]}
        >
          <Input.Password prefix={<LockOutlined />} placeholder="至少 6 位" autoComplete="new-password" />
        </Form.Item>
        <Form.Item
          name="confirm"
          label="确认新密码"
          dependencies={['new_password']}
          rules={[
            { required: true, message: '请再输入一次新密码' },
            ({ getFieldValue }) => ({
              validator(_, value) {
                if (!value || getFieldValue('new_password') === value) return Promise.resolve()
                return Promise.reject(new Error('两次输入的密码不一致'))
              },
            }),
          ]}
        >
          <Input.Password prefix={<LockOutlined />} placeholder="再输入一次新密码" autoComplete="new-password" />
        </Form.Item>
      </Form>
    </Modal>
  )
}
