/**
 * 知识库管理页(仅管理员可见)
 * ==========================
 * 小白理解:这是"资料室的管理台",可以看到:
 *   顶部  —— 四个数字:多少份文档、处理中几份、失败几份、总共多少知识卡片
 *   中间  —— 拖拽上传区:把商品资料拖进来就开始自动处理
 *   下面  —— 文档清单:每份文件的状态、进度条、删除和重试按钮
 *
 * 处理中的文档会自动刷新进度(每 2 秒问一次后端),处理完就停下来,不浪费资源。
 */
import { useCallback, useEffect, useState } from 'react'
import {
  App,
  Button,
  Card,
  Col,
  Empty,
  Popconfirm,
  Progress,
  Row,
  Space,
  Statistic,
  Table,
  Tag,
  Tooltip,
  Typography,
  Upload,
} from 'antd'
import type { UploadProps } from 'antd'
import {
  CheckCircleOutlined,
  ClockCircleOutlined,
  CloseCircleOutlined,
  DatabaseOutlined,
  DeleteOutlined,
  FileTextOutlined,
  InboxOutlined,
  ReloadOutlined,
  SyncOutlined,
} from '@ant-design/icons'
import { formatSize, kbApi, type KbDocument, type KbStats } from '../api/kb'
import { getErrorMessage } from '../api/client'

const { Dragger } = Upload
const { Text } = Typography

/** 把后端返回的时间转成"年-月-日 时:分" */
function formatTime(iso: string): string {
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/** 根据状态显示不同的彩色标签 */
function StatusTag({ doc }: { doc: KbDocument }) {
  switch (doc.status) {
    case 'completed':
      return <Tag icon={<CheckCircleOutlined />} color="success">已完成</Tag>
    case 'failed':
      return (
        <Tooltip title={doc.error_msg || '未知错误'}>
          <Tag icon={<CloseCircleOutlined />} color="error">
            失败
          </Tag>
        </Tooltip>
      )
    case 'processing':
      return <Tag icon={<SyncOutlined spin />} color="processing">处理中</Tag>
    default:
      return <Tag icon={<ClockCircleOutlined />} color="default">排队中</Tag>
  }
}

export default function KnowledgePage() {
  const { message } = App.useApp()

  const [docs, setDocs] = useState<KbDocument[]>([]) // 文档列表
  const [stats, setStats] = useState<KbStats | null>(null) // 顶部统计
  const [loading, setLoading] = useState(true) // 首次加载中
  const [uploading, setUploading] = useState(false) // 是否正在上传

  /** 从后端拉取最新数据(列表 + 统计) */
  const refresh = useCallback(async () => {
    try {
      const [list, st] = await Promise.all([kbApi.list(), kbApi.stats()])
      setDocs(list)
      setStats(st)
    } catch (err) {
      message.error(getErrorMessage(err))
    } finally {
      setLoading(false)
    }
  }, [message])

  // 页面打开时加载一次
  useEffect(() => {
    refresh()
  }, [refresh])

  // 只要还有文档在排队/处理中,就每 2 秒自动刷新一次进度
  useEffect(() => {
    const busy = docs.some((d) => d.status === 'pending' || d.status === 'processing')
    if (!busy) return

    const timer = setInterval(refresh, 2000)
    return () => clearInterval(timer) // 组件关闭或处理完时清理定时器
  }, [docs, refresh])

  /** 上传文件:交给后端后台处理,这里只负责发起和提示 */
  const handleUpload: UploadProps['beforeUpload'] = async (file) => {
    setUploading(true)
    try {
      await kbApi.upload(file)
      message.success(`「${file.name}」已上传,正在后台解析入库`)
      await refresh()
    } catch (err) {
      message.error(getErrorMessage(err))
    } finally {
      setUploading(false)
    }
    return false // 返回 false:阻止 antd 组件自己上传,我们已经处理过了
  }

  /** 删除文档 */
  const handleDelete = async (doc: KbDocument) => {
    try {
      const res = await kbApi.remove(doc.id)
      message.success(res.message)
      await refresh()
    } catch (err) {
      message.error(getErrorMessage(err))
    }
  }

  /** 重新处理 */
  const handleRetry = async (doc: KbDocument) => {
    try {
      const res = await kbApi.retry(doc.id)
      message.success(res.message)
      await refresh()
    } catch (err) {
      message.error(getErrorMessage(err))
    }
  }

  // 表格列定义
  const columns = [
    {
      title: '文件名',
      dataIndex: 'filename',
      key: 'filename',
      render: (name: string, doc: KbDocument) => (
        <Space>
          <FileTextOutlined style={{ color: '#1677ff' }} />
          <span>{name}</span>
          <Tag style={{ marginInlineEnd: 0 }}>{doc.file_type.toUpperCase()}</Tag>
        </Space>
      ),
    },
    {
      title: '大小',
      dataIndex: 'size',
      key: 'size',
      width: 100,
      render: (size: number) => <Text type="secondary">{formatSize(size)}</Text>,
    },
    {
      title: '状态',
      key: 'status',
      width: 190,
      render: (_: unknown, doc: KbDocument) => (
        <Space direction="vertical" size={2} style={{ width: '100%' }}>
          <StatusTag doc={doc} />
          {/* 处理中才显示进度条 */}
          {doc.status === 'processing' && (
            <Progress percent={doc.progress} size="small" style={{ marginBottom: 0 }} />
          )}
        </Space>
      ),
    },
    {
      title: '知识卡片',
      dataIndex: 'chunk_count',
      key: 'chunk_count',
      width: 100,
      render: (n: number) => (n > 0 ? <Tag color="blue">{n} 张</Tag> : <Text type="secondary">—</Text>),
    },
    {
      title: '上传时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 150,
      render: (t: string) => <Text type="secondary">{formatTime(t)}</Text>,
    },
    {
      title: '操作',
      key: 'action',
      width: 140,
      render: (_: unknown, doc: KbDocument) => (
        <Space>
          {/* 失败或已完成都可以重新处理(失败重试 / 内容更新后重新入库) */}
          {doc.status !== 'processing' && (
            <Tooltip title={doc.status === 'failed' ? '重新处理' : '重新入库'}>
              <Button type="text" size="small" icon={<ReloadOutlined />} onClick={() => handleRetry(doc)} />
            </Tooltip>
          )}
          <Popconfirm
            title="确认删除这份文档?"
            description="它的全部知识卡片也会一并清除,不可恢复"
            okText="删除"
            cancelText="取消"
            okButtonProps={{ danger: true }}
            onConfirm={() => handleDelete(doc)}
          >
            <Button type="text" size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div style={{ padding: 24 }}>
      {/* ---------- 顶部统计卡片 ---------- */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <Card>
            <Statistic title="文档总数" value={stats?.document_count ?? 0} prefix={<FileTextOutlined />} />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="知识卡片"
              value={stats?.chunk_count ?? 0}
              prefix={<DatabaseOutlined />}
              valueStyle={{ color: '#1677ff' }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="处理中"
              value={stats?.processing_count ?? 0}
              prefix={<SyncOutlined />}
              valueStyle={{ color: stats?.processing_count ? '#1677ff' : undefined }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="处理失败"
              value={stats?.failed_count ?? 0}
              prefix={<CloseCircleOutlined />}
              valueStyle={{ color: stats?.failed_count ? '#ff4d4f' : undefined }}
            />
          </Card>
        </Col>
      </Row>

      {/* ---------- 上传区 ---------- */}
      <Card style={{ marginBottom: 16 }}>
        <Dragger
          multiple
          showUploadList={false}
          beforeUpload={handleUpload}
          accept=".pdf,.docx,.txt,.md,.xlsx,.csv"
          disabled={uploading}
        >
          <p className="ant-upload-drag-icon">
            <InboxOutlined />
          </p>
          <p className="ant-upload-text">点击或拖拽文件到这里上传</p>
          <p className="ant-upload-hint">
            支持 PDF、Word、Excel、TXT、Markdown,单个文件不超过 20MB。
            上传后系统会自动解析、切分并存入知识库(可一次选择多个文件)。
          </p>
        </Dragger>
      </Card>

      {/* ---------- 文档列表 ---------- */}
      <Card
        title="文档列表"
        extra={
          <Button icon={<ReloadOutlined />} onClick={refresh} loading={loading}>
            刷新
          </Button>
        }
      >
        <Table
          rowKey="id"
          columns={columns}
          dataSource={docs}
          loading={loading}
          pagination={{ pageSize: 10, hideOnSinglePage: true }}
          locale={{
            emptyText: <Empty description="还没有上传任何文档,把商品资料拖到上面的框里试试" />,
          }}
        />
      </Card>
    </div>
  )
}
