export const VERDICT_STATUS = {
  unknown: { label: 'Нет данных', tone: 'none' },
  ok: { label: 'В норме', tone: 'ok' },
  warning: { label: 'Есть отклонения', tone: 'warning' },
  critical: { label: 'Критично', tone: 'critical' },
}

export const SEVERITY = {
  critical: 'Критично',
  warning: 'Предупреждение',
  info: 'Информация',
}

export const OBSERVABILITY = {
  high: 'Хорошо видно камерами',
  medium: 'Видно частично',
  low: 'Видно слабо',
  none: 'Не видно камерами',
}

export const ACTIVITY = {
  working: 'работает',
  idle: 'стоит',
  unknown: 'нет истории',
}

export const RISK = {
  unknown: 'Риск не определён',
  low: 'Низкий риск задержки',
  medium: 'Средний риск задержки',
  high: 'Высокий риск задержки',
}

export const SOURCE_TYPES = [
  { key: 'upload', label: 'Ручная загрузка снимков' },
  { key: 'emulator', label: 'Эмулятор камеры (лента кадров)' },
  { key: 'http', label: 'IP-камера: адрес снимка (HTTP)' },
  { key: 'rtsp', label: 'IP-камера: видеопоток (RTSP)' },
]

// Цвета рамок техники: различимы между собой и на фоне грунта/снега
const PALETTE = ['#E9C46A', '#7FB2F0', '#F08A7A', '#8CD3A3', '#C3A6F2', '#F2A65A', '#6FD1CC', '#F28DB2',
  '#A7D8F0', '#C9E58C', '#E0B3F5', '#F5DE8C', '#79C99A', '#B8BEC2']

export const PCT = (v) => (v === null || v === undefined ? '—' : `${v}%`)

export function classColor(cls, classes) {
  const i = Math.max(0, (classes || []).indexOf(cls))
  return PALETTE[i % PALETTE.length]
}

// Статусы таймлайна под тёмную тему (цвета бэкенда рассчитаны на печатный отчёт)
export const TIMELINE_COLORS = {
  planned: '#4A545B',
  awaiting: '#6C767D',
  on_track: '#8CC39D',
  at_risk: '#F0A553',
  delayed: '#EE7A67',
  done: '#CDB78F',
  ahead: '#7FC6C2',
  unobservable: '#A99BD0',
  unconfirmed: '#B9A077',
}

export function timelineColor(status, fallback) {
  return TIMELINE_COLORS[status] || fallback || '#6C767D'
}
