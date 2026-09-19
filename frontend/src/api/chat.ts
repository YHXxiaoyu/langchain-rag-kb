/**
 * 会话与问答接口封装
 * ==================
 * 小白理解:这里的 chatStream 函数是"流式接收"的关键 ——
 * 它像接水管一样,AI 写一个字,我们就收一个字,立刻显示到屏幕上,
 * 而不是等 AI 全部写完才一次性显示。
 */
import { api } from './client'
import { useAuthStore } from '../stores/authStore'

/** 一条引用资料(AI 回答参考的知识片段) */
export interface Citation {
  index: number      // 编号,对应回答里的 [1] [2]
  filename: string   // 来自哪份文档
  content: string    // 片段原文
  page: number | null // 页码(如果有)
  score: number      // 相关度分数
  document_id: number
  vector_rank: number | null  // 在向量检索里的排名(从 0 开始)
  bm25_rank: number | null    // 在关键词检索里的排名
}

/** 一条聊天消息 */
export interface ChatMessage {
  id: number
  role: 'user' | 'assistant'
  content: string
  citations: Citation[] | null
  feedback: string | null
  created_at: string
}

/** 一个会话 */
export interface Conversation {
  id: number
  title: string
  created_at: string
  updated_at: string
}

/** 流式回答的结束信息 */
export interface StreamDoneInfo {
  message_id: number
  conversation_id: number
  tokens: { tokens?: number; prompt_tokens?: number; completion_tokens?: number }
  cached?: boolean // true = 这次回答来自缓存(没调用 AI,秒回)
}

export const conversationApi = {
  /** 会话列表 */
  list: () => api.get<Conversation[]>('/conversations').then((r) => r.data),
  /** 新建会话 */
  create: (title = '新对话') => api.post<Conversation>('/conversations', { title }).then((r) => r.data),
  /** 重命名 */
  rename: (id: number, title: string) =>
    api.patch<Conversation>(`/conversations/${id}`, { title }).then((r) => r.data),
  /** 删除 */
  remove: (id: number) => api.delete<{ message: string }>(`/conversations/${id}`).then((r) => r.data),
  /** 某会话的历史消息 */
  messages: (id: number) => api.get<ChatMessage[]>(`/conversations/${id}/messages`).then((r) => r.data),
}

export const chatApi = {
  /** 点赞 / 点踩 */
  feedback: (messageId: number, value: 'like' | 'dislike' | 'none') =>
    api.post<{ message: string }>(`/messages/${messageId}/feedback`, { feedback: value }).then((r) => r.data),
}

/** 流式提问时的回调集合 */
export interface StreamHandlers {
  /** 收到引用资料时(第二个参数是系统改写后的检索语句,可能为空) */
  onCitations: (citations: Citation[], searchQuery?: string) => void
  onDelta: (text: string) => void          // 每收到一小段文字时
  onDone: (info: StreamDoneInfo) => void   // 回答结束时
}

/**
 * 发起提问并流式接收回答。
 * 返回一个"停止函数",用户点"停止生成"时可以中断。
 */
export function streamChat(
  question: string,
  conversationId: number | null,
  handlers: StreamHandlers,
): { abort: () => void; promise: Promise<void> } {
  const controller = new AbortController()
  const token = useAuthStore.getState().token

  const promise = (async () => {
    const resp = await fetch('/api/chat', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ question, conversation_id: conversationId }),
      signal: controller.signal,
    })

    if (!resp.ok) {
      // 出错时后端返回的是普通 JSON(不是流),把提示语提取出来
      let detail = `请求失败(HTTP ${resp.status})`
      try {
        const data = await resp.json()
        if (typeof data.detail === 'string') detail = data.detail
      } catch {
        /* 忽略解析错误,用默认提示 */
      }
      throw new Error(detail)
    }

    const reader = resp.body?.getReader()
    if (!reader) throw new Error('浏览器不支持流式读取')

    const decoder = new TextDecoder()
    let buffer = ''

    // 循环读取数据流,按 SSE 规则(两个换行分隔一条消息)拆解
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const parts = buffer.split('\n\n')
      buffer = parts.pop() ?? '' // 最后一段可能不完整,留到下次拼接

      for (const part of parts) {
        const line = part.trim()
        if (!line.startsWith('data: ')) continue

        try {
          const event = JSON.parse(line.slice(6))
          if (event.type === 'citations') handlers.onCitations(event.data ?? [], event.search_query)
          else if (event.type === 'delta') handlers.onDelta(event.content ?? '')
          else if (event.type === 'done') handlers.onDone(event)
        } catch {
          // 单条数据解析失败不影响整体,跳过即可
        }
      }
    }
  })()

  return {
    abort: () => controller.abort(),
    promise,
  }
}
