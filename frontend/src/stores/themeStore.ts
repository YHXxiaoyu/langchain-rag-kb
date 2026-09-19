/**
 * 主题管理(浅色 / 深色)
 * =====================
 * 小白理解:记住用户喜欢"白底黑字"还是"黑底白字",并存在浏览器里,
 * 下次打开还是上次选择的样子。
 */
import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface ThemeState {
  dark: boolean            // true = 深色模式
  toggle: () => void       // 切换
}

export const useThemeStore = create<ThemeState>()(
  persist(
    (set) => ({
      dark: false,
      toggle: () => set((s) => ({ dark: !s.dark })),
    }),
    { name: 'xiaoyu-rag-theme' },
  ),
)
