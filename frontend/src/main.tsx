/**
 * 前端入口
 * ========
 * 小白理解:这是页面的"总装配车间"。React 从这里开始,把整个应用
 * 挂到 index.html 里那个空的 <div id="root"> 上。
 *
 * 三层"外包装"的作用:
 *   ConfigProvider —— 统一外观(中文语言包 + 主题色 + 明暗模式)
 *   AntdApp        —— 提供弹窗提示(message/notification)的运行环境
 *   App            —— 我们自己的应用(内部包含路由)
 */
import React from 'react'
import ReactDOM from 'react-dom/client'
import { App as AntdApp, ConfigProvider, theme } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import App from './App'
import { useThemeStore } from './stores/themeStore'
import './index.css'

/** 根组件:负责根据"深色/浅色"设置自动切换整套界面配色 */
function Root() {
  const dark = useThemeStore((s) => s.dark)

  // 切换浏览器根元素的 class,供自定义样式(index.css 里的 CSS 变量)响应
  React.useEffect(() => {
    document.body.className = dark ? 'dark' : ''
  }, [dark])

  return (
    <ConfigProvider
      locale={zhCN}
      theme={{
        // antd 自带两套配色算法:defaultAlgorithm=浅色,darkAlgorithm=深色
        algorithm: dark ? theme.darkAlgorithm : theme.defaultAlgorithm,
        token: {
          colorPrimary: '#1677ff', // 主色调:企业蓝
          borderRadius: 8,
        },
      }}
    >
      <AntdApp>
        <App />
      </AntdApp>
    </ConfigProvider>
  )
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <Root />
  </React.StrictMode>,
)
