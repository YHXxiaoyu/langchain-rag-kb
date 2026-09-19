/**
 * 知识库管理接口封装(仅管理员可用)
 * =================================
 */
import { api } from './client'

/** 一份文档的信息 */
export interface KbDocument {
  id: number
  filename: string
  file_type: string
  size: number
  status: 'pending' | 'processing' | 'completed' | 'failed'
  progress: number
  chunk_count: number
  error_msg: string | null
  created_at: string
}

/** 知识库总览统计 */
export interface KbStats {
  document_count: number
  completed_count: number
  processing_count: number
  failed_count: number
  chunk_count: number
  total_size: number
}

export const kbApi = {
  /** 文档列表 */
  list: () => api.get<KbDocument[]>('/kb/documents').then((r) => r.data),

  /** 上传单个文件(后端支持一次传多个,这里逐个传以便显示每份文件的进度) */
  upload: (file: File) => {
    const formData = new FormData()
    formData.append('files', file)
    // 上传大文件可能较慢,单独放宽超时到 5 分钟
    return api
      .post<KbDocument[]>('/kb/documents', formData, { timeout: 300000 })
      .then((r) => r.data)
  },

  /** 删除文档(连同它的知识卡片一起清掉) */
  remove: (id: number) => api.delete<{ message: string }>(`/kb/documents/${id}`).then((r) => r.data),

  /** 重新处理(失败重试 / 重新入库) */
  retry: (id: number) => api.post<{ message: string }>(`/kb/documents/${id}/retry`).then((r) => r.data),

  /** 知识库总览统计 */
  stats: () => api.get<KbStats>('/kb/stats').then((r) => r.data),
}

/** 把字节数变成看得懂的大小文字,如 "1.2 MB" */
export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}
