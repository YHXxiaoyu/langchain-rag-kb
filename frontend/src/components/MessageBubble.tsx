/**
 * 消息气泡(一问一答的展示样式)
 * ============================
 * 小白理解:
 *   用户的提问 —— 靠右,蓝色气泡
 *   AI 的回答 —— 靠左,白底卡片,支持 Markdown 排版(列表、加粗等)
 *
 * AI 回答里的 [1] [2] 会被渲染成蓝色小标签,提醒用户"这句话有出处"。
 */
import { useState } from 'react'
import { App, Button, Space, Tooltip, Typography } from 'antd'
import { DislikeFilled, DislikeOutlined, LikeFilled, LikeOutlined, UserOutlined } from '@ant-design/icons'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { ChatMessage, Citation } from '../api/chat'
import { chatApi } from '../api/chat'
import { getErrorMessage } from '../api/client'
import CitationList from './CitationList'

const { Text } = Typography

interface Props {
  message: ChatMessage
  /** 流式输出中的消息(还没有真实编号,不能点赞) */
  streaming?: boolean
  /** 流式中已收到的引用资料 */
  streamingCitations?: Citation[]
  /** 检索时系统对问题的理解(问题被改写时展示,体现检索过程) */
  searchQuery?: string
}

/**
 * 把回答里的 [1] 变成 Markdown 链接语法,这样才能在渲染时变成可点击的标签。
 * 例:"电池是5000mAh [1]" → "电池是5000mAh [[1]](#cite-1)"
 */
function markCitations(text: string): string {
  return text.replace(/\[(\d+)\]/g, '[[$1]](#cite-$1)')
}

export default function MessageBubble({ message, streaming = false, streamingCitations, searchQuery }: Props) {
  const { message: toast } = App.useApp()
  const [feedback, setFeedback] = useState<string | null>(message.feedback)

  const isUser = message.role === 'user'
  const citations = streaming ? (streamingCitations ?? []) : (message.citations ?? [])

  /** 点赞 / 点踩(再点一次取消) */
  const handleFeedback = async (value: 'like' | 'dislike') => {
    if (streaming || message.id <= 0) return
    const next = feedback === value ? 'none' : value
    try {
      await chatApi.feedback(message.id, next)
      setFeedback(next === 'none' ? null : next)
      toast.success(next === 'none' ? '已取消评价' : '感谢反馈!')
    } catch (err) {
      toast.error(getErrorMessage(err))
    }
  }

  // ---------- 用户提问:右侧蓝气泡 ----------
  if (isUser) {
    return (
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 20 }}>
        <div style={{ display: 'flex', gap: 10, maxWidth: '76%' }}>
          <div
            style={{
              background: '#1677ff',
              color: '#fff',
              padding: '10px 16px',
              borderRadius: '12px 12px 2px 12px',
              whiteSpace: 'pre-wrap',
              lineHeight: 1.7,
            }}
          >
            {message.content}
          </div>
          <div
            style={{
              width: 32,
              height: 32,
              borderRadius: '50%',
              background: '#e6f4ff',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              flexShrink: 0,
            }}
          >
            <UserOutlined style={{ color: '#1677ff' }} />
          </div>
        </div>
      </div>
    )
  }

  // ---------- AI 回答:左侧卡片 ----------
  return (
    <div style={{ display: 'flex', gap: 10, marginBottom: 20, maxWidth: '86%' }}>
      <div
        style={{
          width: 32,
          height: 32,
          borderRadius: '50%',
          background: 'rgba(250, 173, 20, 0.15)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontSize: 18,
          flexShrink: 0,
        }}
      >
        🐟
      </div>

      <div style={{ flex: 1, minWidth: 0 }}>
        <div
          style={{
            background: 'var(--bg-bubble-ai)',
            padding: '12px 16px',
            borderRadius: '2px 12px 12px 12px',
            boxShadow: '0 1px 4px rgba(0,0,0,0.06)',
          }}
        >
          {/* 回答正文(Markdown 渲染) */}
          <div className="markdown-body">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                // 把引用标记 [1] 渲染成蓝色小标签
                a: ({ href, children }) => {
                  if (href?.startsWith('#cite-')) {
                    return <span className="cite-ref">{children}</span>
                  }
                  return (
                    <a href={href} target="_blank" rel="noreferrer">
                      {children}
                    </a>
                  )
                },
              }}
            >
              {markCitations(message.content)}
            </ReactMarkdown>
            {/* 流式输出中的闪烁光标 */}
            {streaming && <span className="streaming-cursor">▍</span>}
          </div>

          {/* 检索过程可视化:当系统改写了问题(比如把"它"替换成具体商品名),这里如实展示 */}
          {streaming && searchQuery && (
            <Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 8 }}>
              🔄 检索理解为:{searchQuery}
            </Text>
          )}

          {/* 引用资料 */}
          {citations.length > 0 && <CitationList citations={citations} />}
        </div>

        {/* 点赞 / 点踩(流式输出中不显示) */}
        {!streaming && message.id > 0 && (
          <Space size={4} style={{ marginTop: 6, marginLeft: 4 }}>
            <Text type="secondary" style={{ fontSize: 12 }}>
              这个回答有帮助吗?
            </Text>
            <Tooltip title="有帮助">
              <Button
                type="text"
                size="small"
                icon={feedback === 'like' ? <LikeFilled style={{ color: '#52c41a' }} /> : <LikeOutlined />}
                onClick={() => handleFeedback('like')}
              />
            </Tooltip>
            <Tooltip title="没帮助">
              <Button
                type="text"
                size="small"
                icon={feedback === 'dislike' ? <DislikeFilled style={{ color: '#ff4d4f' }} /> : <DislikeOutlined />}
                onClick={() => handleFeedback('dislike')}
              />
            </Tooltip>
          </Space>
        )}
      </div>
    </div>
  )
}
