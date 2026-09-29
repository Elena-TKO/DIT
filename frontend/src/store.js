import { reactive } from 'vue'

const saved = (() => {
  try { return JSON.parse(localStorage.getItem('sk-session') || 'null') } catch { return null }
})()

export const session = reactive({
  token: saved?.token || null,
  user: saved?.user || null,
})

export function setSession(data) {
  session.token = data?.token || null
  session.user = data?.user || null
  if (session.token) localStorage.setItem('sk-session', JSON.stringify({ token: session.token, user: session.user }))
  else localStorage.removeItem('sk-session')
}

/** Состояние навигации: хлебные крошки, текущая стройка/объект, счётчик для обновления боковой панели. */
export const ui = reactive({ crumbs: [], projectId: null, buildingId: null, navVersion: 0 })

/** Дизайн интерфейса: 'light' — новый светлый, 'classic' — тёмный, как до редизайна. Хранится в браузере. */
export const DESIGNS = [
  { key: 'light', label: 'Новый' },
  { key: 'classic', label: 'Классический' },
]
const savedDesign = (() => {
  try { return localStorage.getItem('sk-design') } catch { return null }
})()
ui.design = DESIGNS.some((d) => d.key === savedDesign) ? savedDesign : 'light'

export function setDesign(key) {
  if (!DESIGNS.some((d) => d.key === key)) return
  ui.design = key
  try { localStorage.setItem('sk-design', key) } catch { /* приватный режим — только до перезагрузки */ }
}

export function refreshNav() {
  ui.navVersion += 1
}
