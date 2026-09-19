/**
 * 智能问答页(系统的主界面)
 * ========================
 * 布局:
 *   ┌────────────┬──────────────────────────────┐
 *   │  会话列表   │  聊天窗口                     │
 *   │  [+ 新对话] │   ……消息气泡……                │
 *   │  会话1      │   ┌──────────────────────┐   │
 *   │  会话2      │   │ 输入框        [发送] │   │
 *   └────────────┴──────────────────────────────┘
 *
 * 交互要点:
 *   - Enter 发送,Shift+Enter 换行
 *   - AI 回答边写边显示(打字机效果),可以中途点"停止生成"
 *   - 回答下方展示引用了哪些知识片段
 *   - 历史会话随时切换,消息从数据库读取(重登也在)
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { App, Button, Input, Popconfirm, Space, Spin, Tooltip, Typography } from 'antd'
import {
  DeleteOutlined,
  DownloadOutlined,
  MessageOutlined,
  PlusOutlined,
  SendOutlined,
  StopOutlined,
} from '@ant-design/icons'
import {
  conversationApi,
  streamChat,
  type Citation,
  type ChatMessage,
  type Conversation,
} from '../api/chat'
import { getErrorMessage } from '../api/client'
import MessageBubble from '../components/MessageBubble'

const { Text, Title, Paragraph } = Typography

/** 新手引导:示例问题(点一下就能问) */
const SAMPLE_QUESTIONS = [
  '星辰X1手机的电池容量是多少?',
  '笔记本保修几年?',
  '七天无理由退货有什么条件?',
  '耳机怎么连接蓝牙?',
]

export default function ChatPage() {
  const { message: toast, modal } = App.useApp()

  // ---------- 会话相关 ----------
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [activeId, setActiveId] = useState<number | null>(null) // 当前选中的会话编号

  // ---------- 消息相关 ----------
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [loadingMsgs, setLoadingMsgs] = useState(false)

  // ---------- 提问相关 ----------
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)             // 是否正在生成回答
  const [streamText, setStreamText] = useState('')          // 正在流式接收的文字
  const [streamCitations, setStreamCitations] = useState<Citation[]>([]) // 正在接收的引用
  const [searchQuery, setSearchQuery] = useState('')        // 系统改写后的检索语句

  const abortRef = useRef<(() => void) | null>(null) // 用于"停止生成"
  const bottomRef = useRef<HTMLDivElement>(null)    // 用于自动滚动到底部

  /** 拉取会话列表 */
  const loadConversations = useCallback(async () => {
    const list = await conversationApi.list()
    setConversations(list)
    return list
  }, [])

  // 页面打开时:加载会话列表,并默认打开第一个会话
  useEffect(() => {
    loadConversations()
      .then((list) => {
        if (list.length > 0) setActiveId(list[0].id)
      })
      .catch((err) => toast.error(getErrorMessage(err)))
  }, [loadConversations, toast])

  // 切换会话时:加载该会话的历史消息
  useEffect(() => {
    if (activeId === null) {
      setMessages([])
      return
    }
    setLoadingMsgs(true)
    conversationApi
      .messages(activeId)
      .then(setMessages)
      .catch((err) => toast.error(getErrorMessage(err)))
      .finally(() => setLoadingMsgs(false))
  }, [activeId, toast])

  // 有新内容时自动滚动到最底部
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages, streamText])

  /** 发送提问 */
  const handleSend = async (question?: string) => {
    const text = (question ?? input).trim()
    if (!text || sending) return

    setInput('')
    setSending(true)
    setStreamText('')
    setStreamCitations([])

    // ① 立刻把用户的问题显示出来(不等服务器)
    const tempMsg: ChatMessage = {
      id: -Date.now(), // 临时编号(负数,与服务器编号区分)
      role: 'user',
      content: text,
      citations: null,
      feedback: null,
      created_at: new Date().toISOString(),
    }
    setMessages((prev) => [...prev, tempMsg])

    // ② 发起流式提问
    let convId = activeId
    try {
      const { abort, promise } = streamChat(text, activeId, {
        onCitations: (c, sq) => {
          setStreamCitations(c)
          setSearchQuery(sq ?? '')
        },
        onDelta: (t) => setStreamText((prev) => prev + t),
        onDone: (info) => {
          convId = info.conversation_id
          // 命中缓存时给用户一个明确反馈,体现"秒回"的优化效果
          if (info.cached) toast.success('⚡ 命中缓存,秒回(未消耗 AI 额度)')
        },
      })
      abortRef.current = abort
      await promise

      // ③ 回答完毕:刷新会话列表(新会话会出现在最前,标题也更新了)
      await loadConversations()
      // 用服务器上的真实数据刷新消息(拿到真实编号和完整引用信息)
      const targetId = convId ?? activeId
      if (targetId && targetId !== activeId) {
        setActiveId(targetId) // 首次提问自动创建的会话:切换过去,useEffect 会自动加载消息
      } else if (targetId) {
        const msgs = await conversationApi.messages(targetId)
        setMessages(msgs)
      } else {
        // 没有会话编号(异常情况):清掉临时显示的消息
        setMessages((prev) => prev.filter((m) => m.id > 0))
      }
    } catch (err) {
      // 用户主动停止不算错误
      if ((err as Error)?.name === 'AbortError') {
        toast.info('已停止生成')
      } else {
        toast.error(getErrorMessage(err) || (err as Error).message)
      }
      // 出错时清掉这次未完成的对话显示
      setMessages((prev) => prev.filter((m) => m.id > 0))
    } finally {
      setSending(false)
      setStreamText('')
      setStreamCitations([])
      setSearchQuery('')
      abortRef.current = null
    }
  }

  /** 导出当前对话为 Markdown 文件(可用记事本、Typora 等打开) */
  const handleExport = () => {
    const title = activeConv?.title ?? '新对话'
    const lines: string[] = [`# ${title}`, '', `> 导出时间:${new Date().toLocaleString('zh-CN')}`, '']

    for (const m of messages) {
      if (m.role === 'user') {
        lines.push('## 🙋 我的提问', '', m.content, '')
      } else {
        lines.push('## 🐟 小鱼助手', '', m.content, '')
        // 附上参考资料清单(体现"回答有据可查")
        if (m.citations?.length) {
          lines.push('', '**参考资料**', '')
          for (const c of m.citations) {
            const page = c.page ? ` 第 ${c.page} 页` : ''
            lines.push(`- [${c.index}] 《${c.filename}》${page}(相关度 ${(c.score * 100).toFixed(0)}%)`)
          }
        }
        lines.push('')
      }
      lines.push('---', '')
    }

    // 生成文件并触发浏览器下载
    const blob = new Blob([lines.join('\n')], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${title}.md`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
    toast.success('对话已导出为 Markdown 文件')
  }

  /** 停止生成 */
  const handleStop = () => {
    abortRef.current?.()
  }

  /** 新建会话 */
  const handleNewConversation = () => {
    setActiveId(null)
    setMessages([])
    setStreamText('')
    setStreamCitations([])
  }

  /** 删除会话 */
  const handleDeleteConversation = async (conv: Conversation) => {
    try {
      const res = await conversationApi.remove(conv.id)
      toast.success(res.message)
      const list = await loadConversations()
      // 如果删的是当前会话,切换到第一个(或清空)
      if (conv.id === activeId) {
        setActiveId(list.length > 0 ? list[0].id : null)
      }
    } catch (err) {
      toast.error(getErrorMessage(err))
    }
  }

  /** 重命名会话(双击标题触发) */
  const handleRename = (conv: Conversation) => {
    let newTitle = conv.title
    modal.confirm({
      title: '重命名会话',
      icon: null,
      content: (
        <Input
          defaultValue={conv.title}
          onChange={(e) => {
            newTitle = e.target.value
          }}
          style={{ marginTop: 12 }}
          maxLength={100}
        />
      ),
      okText: '保存',
      cancelText: '取消',
      onOk: async () => {
        const title = newTitle.trim()
        if (!title) {
          toast.warning('标题不能为空')
          return Promise.reject()
        }
        try {
          await conversationApi.rename(conv.id, title)
          await loadConversations()
          toast.success('已重命名')
        } catch (err) {
          toast.error(getErrorMessage(err))
          return Promise.reject()
        }
      },
    })
  }

  const isEmpty = messages.length === 0 && !sending
  // 当前打开的会话(用于顶部标题栏)
  const activeConv = conversations.find((c) => c.id === activeId) ?? null

  return (
    <div style={{ display: 'flex', height: 'calc(100vh - 56px)', background: 'var(--bg-chat)' }}>
      {/* ==================== 左侧:会话列表 ==================== */}
      <div
        style={{
          width: 236,
          borderRight: '1px solid var(--border-soft)',
          display: 'flex',
          flexDirection: 'column',
          background: 'var(--bg-sidebar)',
        }}
      >
        <div style={{ padding: 12 }}>
          <Button type="primary" block icon={<PlusOutlined />} onClick={handleNewConversation}>
            新对话
          </Button>
        </div>

        <div style={{ flex: 1, overflowY: 'auto', padding: '0 8px 12px' }}>
          {conversations.length === 0 ? (
            <Text type="secondary" style={{ fontSize: 12, padding: 8, display: 'block' }}>
              还没有会话,点上方"新对话"开始提问吧
            </Text>
          ) : (
            conversations.map((conv) => {
              const active = conv.id === activeId
              return (
                <div
                  key={conv.id}
                  onClick={() => {
                    // 正在生成回答时不允许切换会话,避免文字"串台"
                    if (sending) {
                      toast.warning('回答生成中,请先点击"停止"或稍候')
                      return
                    }
                    setActiveId(conv.id)
                  }}
                  onDoubleClick={() => handleRename(conv)}
                  style={{
                    padding: '9px 10px',
                    marginBottom: 4,
                    borderRadius: 8,
                    cursor: 'pointer',
                    background: active ? 'var(--cite-bg)' : 'transparent',
                    display: 'flex',
                    alignItems: 'center',
                    gap: 8,
                  }}
                >
                  <MessageOutlined style={{ color: active ? '#1677ff' : '#999', fontSize: 13 }} />
                  <Tooltip title={`${conv.title}(双击可重命名)`} mouseEnterDelay={0.8}>
                    <span
                      style={{
                        flex: 1,
                        fontSize: 13,
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap',
                        color: active ? 'var(--cite-color)' : 'var(--text-body)',
                      }}
                    >
                      {conv.title}
                    </span>
                  </Tooltip>
                  <Popconfirm
                    title="删除这个会话?"
                    description="聊天记录会一并删除"
                    okText="删除"
                    cancelText="取消"
                    okButtonProps={{ danger: true }}
                    onConfirm={() => handleDeleteConversation(conv)}
                  >
                    <DeleteOutlined
                      onClick={(e) => e.stopPropagation()}
                      style={{ color: '#bbb', fontSize: 12, opacity: active ? 1 : 0.6 }}
                    />
                  </Popconfirm>
                </div>
              )
            })
          )}
        </div>
      </div>

      {/* ==================== 右侧:聊天窗口 ==================== */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
        {/* 顶部工具栏:当前会话标题 + 导出按钮 */}
        <div
          style={{
            height: 44,
            flexShrink: 0,
            borderBottom: '1px solid var(--border-soft)',
            padding: '0 20px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          <Text strong style={{ fontSize: 14 }}>
            {activeConv?.title ?? '新对话'}
          </Text>
          <Tooltip title="把当前对话(含引用来源)导出为 Markdown 文件">
            <Button
              size="small"
              icon={<DownloadOutlined />}
              onClick={handleExport}
              disabled={messages.length === 0}
            >
              导出对话
            </Button>
          </Tooltip>
        </div>

        {/* 消息区 */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '24px 28px' }}>
          {loadingMsgs ? (
            <div style={{ textAlign: 'center', paddingTop: 80 }}>
              <Spin />
            </div>
          ) : isEmpty ? (
            /* 空状态:欢迎语 + 示例问题 */
            <div style={{ maxWidth: 620, margin: '60px auto 0', textAlign: 'center' }}>
              <div style={{ fontSize: 48, marginBottom: 12 }}>🐟</div>
              <Title level={4} style={{ marginBottom: 8 }}>
                你好,我是小鱼知识库助手
              </Title>
              <Paragraph type="secondary">
                我可以基于知识库里的商品资料回答问题,并告诉你答案来自哪份文档。
              </Paragraph>
              <Space direction="vertical" size={8} style={{ width: '100%', marginTop: 16 }}>
                {SAMPLE_QUESTIONS.map((q) => (
                  <Button
                    key={q}
                    block
                    onClick={() => handleSend(q)}
                    style={{ textAlign: 'left', height: 'auto', padding: '10px 16px' }}
                  >
                    {q}
                  </Button>
                ))}
              </Space>
            </div>
          ) : (
            <>
              {messages.map((msg) => (
                <MessageBubble key={msg.id} message={msg} />
              ))}
              {/* 正在生成的回答 */}
              {sending && (
                <MessageBubble
                  message={{
                    id: -1,
                    role: 'assistant',
                    content: streamText || '正在思考...',
                    citations: null,
                    feedback: null,
                    created_at: new Date().toISOString(),
                  }}
                  streaming
                  streamingCitations={streamCitations}
                  searchQuery={searchQuery}
                />
              )}
            </>
          )}
          <div ref={bottomRef} />
        </div>

        {/* 输入区 */}
        <div style={{ borderTop: '1px solid var(--border-soft)', padding: '12px 28px 16px' }}>
          <div style={{ display: 'flex', gap: 10, alignItems: 'flex-end' }}>
            <Input.TextArea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="输入你的问题,Enter 发送,Shift+Enter 换行"
              autoSize={{ minRows: 1, maxRows: 5 }}
              disabled={sending}
              onPressEnter={(e) => {
                if (!e.shiftKey) {
                  e.preventDefault()
                  handleSend()
                }
              }}
              style={{ borderRadius: 10 }}
            />
            {sending ? (
              <Button danger icon={<StopOutlined />} onClick={handleStop} style={{ height: 38 }}>
                停止
              </Button>
            ) : (
              <Button
                type="primary"
                icon={<SendOutlined />}
                onClick={() => handleSend()}
                disabled={!input.trim()}
                style={{ height: 38 }}
              >
                发送
              </Button>
            )}
          </div>
          <Text type="secondary" style={{ fontSize: 11, display: 'block', marginTop: 6 }}>
            回答由 AI 依据知识库内容生成,重要信息请以商品详情页为准
          </Text>
        </div>
      </div>
    </div>
  )
}
