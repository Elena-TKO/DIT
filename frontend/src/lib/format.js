const MONTHS = ['янв', 'фев', 'мар', 'апр', 'мая', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек']

/** 'YYYY-MM-DD' или ISO → Date в локальном времени без сдвига часового пояса. */
export function parseDate(value) {
  if (!value) return null
  if (value instanceof Date) return value
  const m = String(value).match(/^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2}))?)?/)
  if (!m) return null
  return new Date(+m[1], +m[2] - 1, +m[3], +(m[4] || 0), +(m[5] || 0), +(m[6] || 0))
}

export function formatDate(value) {
  const d = parseDate(value)
  if (!d) return '—'
  return `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`
}

export function formatDateTime(value) {
  const d = parseDate(value)
  if (!d) return '—'
  const hh = String(d.getHours()).padStart(2, '0')
  const mm = String(d.getMinutes()).padStart(2, '0')
  return `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}, ${hh}:${mm}`
}

/** Значение для <input type="datetime-local">. */
export function toLocalInput(value) {
  const d = parseDate(value) || new Date()
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`
}

export function plural(n, one, few, many) {
  const a = Math.abs(n) % 100
  const b = a % 10
  if (a > 10 && a < 20) return many
  if (b > 1 && b < 5) return few
  if (b === 1) return one
  return many
}

export function countLabel(n, one, few, many) {
  return `${n} ${plural(n, one, few, many)}`
}

/** Деньги без копеек, с неразрывными пробелами: 1 250 000 ₽ */
export function money(value, currency = '₽') {
  if (value === null || value === undefined) return '—'
  return `${Math.round(value).toLocaleString('ru-RU').replace(/\s/g, '\u00a0')}\u00a0${currency}`
}
