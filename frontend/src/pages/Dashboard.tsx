/**
 * 数据看板(仅管理员可见)
 * ======================
 * 小白理解:给管理员看的"经营大屏",一眼看清系统的运行情况:
 *   - 有多少用户注册、聊了多少句
 *   - 花了多少 AI 额度(token 消耗)
 *   - 最近一周大家提问的活跃度(柱状图)
 *   - 几项性能优化到底省了多少事(缓存命中率、回答好评率)
 *
 * 这些数据也是评估系统运行状况的现成依据。
 */
import { useEffect, useState } from 'react'
import { App, Card, Col, Empty, Row, Space, Spin, Statistic, Tag, Typography } from 'antd'
import {
  CommentOutlined,
  DatabaseOutlined,
  DislikeOutlined,
  LikeOutlined,
  MessageOutlined,
  ThunderboltOutlined,
  UserOutlined,
  WalletOutlined,
} from '@ant-design/icons'
import { statsApi, type AdminStats } from '../api/stats'
import { getErrorMessage } from '../api/client'

const { Text, Paragraph } = Typography

export default function DashboardPage() {
  const { message } = App.useApp()
  const [data, setData] = useState<AdminStats | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    statsApi
      .get()
      .then(setData)
      .catch((err) => message.error(getErrorMessage(err)))
      .finally(() => setLoading(false))
  }, [message])

  if (loading) {
    return (
      <div style={{ textAlign: 'center', paddingTop: 120 }}>
        <Spin size="large" />
      </div>
    )
  }

  if (!data) {
    return (
      <div style={{ paddingTop: 120 }}>
        <Empty description="暂时拿不到统计数据" />
      </div>
    )
  }

  // 柱状图的高度基准:取一周内的最大提问数(避免除以 0)
  const maxCount = Math.max(...data.daily_trend.map((d) => d.count), 1)

  return (
    <div style={{ padding: 24 }}>
      {/* ---------- 顶部核心数字 ---------- */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <Card>
            <Statistic title="注册用户" value={data.users.total} prefix={<UserOutlined />} />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic title="会话总数" value={data.conversations.total} prefix={<CommentOutlined />} />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="提问次数"
              value={data.messages.questions}
              prefix={<MessageOutlined />}
              valueStyle={{ color: '#1677ff' }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="Token 消耗"
              value={data.tokens.total}
              prefix={<WalletOutlined />}
              valueStyle={{ color: '#fa8c16' }}
              suffix={<Text type="secondary" style={{ fontSize: 12 }}>≈ ¥{(data.tokens.total / 1_000_000 * 1).toFixed(3)}</Text>}
            />
          </Card>
        </Col>
      </Row>

      <Row gutter={16}>
        {/* ---------- 最近一周提问趋势(柱状图) ---------- */}
        <Col span={14}>
          <Card title="最近 7 天提问趋势" style={{ height: '100%' }}>
            <div style={{ display: 'flex', alignItems: 'flex-end', gap: 12, height: 180, paddingTop: 20 }}>
              {data.daily_trend.map((d) => (
                <div key={d.date} style={{ flex: 1, textAlign: 'center' }}>
                  <div style={{ fontSize: 12, marginBottom: 4, color: '#8c8c8c' }}>{d.count}</div>
                  <div
                    style={{
                      height: `${Math.max((d.count / maxCount) * 110, 4)}px`,
                      background: d.count > 0 ? 'linear-gradient(180deg, #4096ff, #1677ff)' : 'var(--border-soft)',
                      borderRadius: '4px 4px 0 0',
                      transition: 'height 0.3s',
                    }}
                  />
                  <div style={{ fontSize: 11, color: '#8c8c8c', marginTop: 6 }}>{d.date}</div>
                </div>
              ))}
            </div>
          </Card>
        </Col>

        {/* ---------- 优化效果与质量 ---------- */}
        <Col span={10}>
          <Card title="系统优化效果" style={{ height: '100%' }}>
            <Space direction="vertical" size="middle" style={{ width: '100%' }}>
              {/* 缓存效果 */}
              <div>
                <Space>
                  <ThunderboltOutlined style={{ color: '#faad14' }} />
                  <Text strong>问答缓存</Text>
                </Space>
                <div style={{ marginTop: 6, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                  <Tag color="gold">命中率 {data.cache.hit_rate}%</Tag>
                  <Tag>命中 {data.cache.hits} 次</Tag>
                  <Tag>缓存中 {data.cache.size} 条</Tag>
                </div>
                <Paragraph type="secondary" style={{ fontSize: 12, marginTop: 6, marginBottom: 0 }}>
                  命中缓存的提问无需调用 AI,响应时间从数秒降至毫秒级,且零成本
                </Paragraph>
              </div>

              {/* 回答质量 */}
              <div>
                <Space>
                  <LikeOutlined style={{ color: '#52c41a' }} />
                  <Text strong>回答质量反馈</Text>
                </Space>
                <div style={{ marginTop: 6, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                  <Tag color="success">
                    <LikeOutlined /> {data.messages.likes}
                  </Tag>
                  <Tag color="error">
                    <DislikeOutlined /> {data.messages.dislikes}
                  </Tag>
                  <Tag color="blue">好评率 {data.messages.like_rate}%</Tag>
                </div>
              </div>

              {/* 知识库规模 */}
              <div>
                <Space>
                  <DatabaseOutlined style={{ color: '#1677ff' }} />
                  <Text strong>知识库规模</Text>
                </Space>
                <div style={{ marginTop: 6, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                  <Tag color="processing">{data.knowledge.documents} 份文档</Tag>
                  <Tag color="processing">{data.knowledge.chunks} 张知识卡片</Tag>
                </div>
              </div>
            </Space>
          </Card>
        </Col>
      </Row>
    </div>
  )
}
