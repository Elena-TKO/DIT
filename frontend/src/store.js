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

export function refreshNav() {
  ui.navVersion += 1
}
