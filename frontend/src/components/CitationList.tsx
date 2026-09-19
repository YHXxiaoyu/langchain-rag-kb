/**
 * 引用资料列表(回答下方的"参考资料"区域)
 * ======================================
 * 小白理解:AI 回答里的 [1] [2] 分别来自哪份文档、原文长什么样,都在这里展示。
 * 点开就能看到原文片段 —— 这就是"回答有据可查",也是本系统的核心特色。
 */
import { Collapse, Tag, Typography } from 'antd'
import { BookOutlined } from '@ant-design/icons'
import type { Citation } from '../api/chat'

const { Text } = Typography

interface Props {
  citations: Citation[]
}

export default function CitationList({ citations }: Props) {
  if (!citations || citations.length === 0) return null

  return (
    <Collapse
      size="small"
      ghost
      style={{ marginTop: 8, background: 'var(--bg-cite-area)', borderRadius: 8 }}
      items={[
        {
          key: 'citations',
          label: (
            <Text style={{ fontSize: 13 }}>
              <BookOutlined style={{ marginRight: 6, color: '#1677ff' }} />
              参考资料({citations.length} 条)
            </Text>
          ),
          children: (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {citations.map((c) => (
                <div
                  key={c.index}
                  style={{
                    borderLeft: '3px solid #1677ff',
                    background: 'var(--bg-cite-item)',
                    padding: '8px 12px',
                    borderRadius: 4,
                  }}
                >
                  {/* 来源信息:编号 + 文件名 + 页码 + 相关度 + 检索排名 */}
                  <div style={{ marginBottom: 6, display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                    <Tag color="blue" style={{ marginInlineEnd: 0 }}>
                      [{c.index}]
                    </Tag>
                    <Text strong style={{ fontSize: 13 }}>
                      {c.filename}
                    </Text>
                    {c.page ? (
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        第 {c.page} 页
                      </Text>
                    ) : null}
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      相关度 {(c.score * 100).toFixed(0)}%
                    </Text>
                    {/* 检索过程透视:让用户看到这段资料是被哪一路检索找到的、排第几 */}
                    {c.vector_rank != null && (
                      <Tag bordered={false} color="geekblue" style={{ fontSize: 11, marginInlineEnd: 0 }}>
                        语义检索第 {c.vector_rank + 1} 名
                      </Tag>
                    )}
                    {c.bm25_rank != null && (
                      <Tag bordered={false} color="purple" style={{ fontSize: 11, marginInlineEnd: 0 }}>
                        关键词检索第 {c.bm25_rank + 1} 名
                      </Tag>
                    )}
                  </div>
                  {/* 原文片段 */}
                  <Text style={{ fontSize: 13, color: '#595959', whiteSpace: 'pre-wrap' }}>
                    {c.content.length > 300 ? `${c.content.slice(0, 300)}...` : c.content}
                  </Text>
                </div>
              ))}
            </div>
          ),
        },
      ]}
    />
  )
}
