import { parseDate } from './format.js'

const DAY = 86400000
const MONTHS = ['янв', 'фев', 'мар', 'апр', 'май', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек']

/** Линейная шкала дат → пиксели. */
export function makeScale(start, end, width) {
  const s = parseDate(start).getTime()
  const e = Math.max(parseDate(end).getTime(), s + DAY)
  const k = width / (e - s)
  return {
    x: (date) => Math.round((parseDate(date).getTime() - s) * k * 10) / 10,
    width,
    days: Math.round((e - s) / DAY),
  }
}

/** Метки месяцев в диапазоне. Годы подписываются всегда, месяцы — если не наезжают. */
export function monthTicks(start, end, width, minGap = 44) {
  const s = parseDate(start)
  const e = parseDate(end)
  const scale = makeScale(start, end, width)
  const ticks = []
  const d = new Date(s.getFullYear(), s.getMonth() + 1, 1)
  while (d <= e) {
    const year = d.getMonth() === 0
    ticks.push({ x: scale.x(d), year, text: year ? String(d.getFullYear()) : MONTHS[d.getMonth()], label: '' })
    d.setMonth(d.getMonth() + 1)
  }
  const labeled = []
  for (const t of ticks.filter((t) => t.year)) {
    t.label = t.text
    labeled.push(t.x)
  }
  for (const t of ticks.filter((t) => !t.year)) {
    if (labeled.every((x) => Math.abs(x - t.x) >= minGap)) {
      t.label = t.text
      labeled.push(t.x)
    }
  }
  return ticks.map(({ x, label, year }) => ({ x, label, year }))
}

/** Полоса этапа/работы: x и ширина не меньше 2px, обрезка по краям. */
export function bar(scale, start, end) {
  const x1 = Math.max(0, scale.x(start))
  const x2 = Math.min(scale.width, scale.x(end))
  return { x: x1, w: Math.max(2, x2 - x1) }
}

/** Доля ширины шкалы (0..1) → дата 'YYYY-MM-DD'. Для линии под курсором на таймлайне. */
export function dateAt(start, end, fraction) {
  const s = parseDate(start).getTime()
  const e = Math.max(parseDate(end).getTime(), s + DAY)
  const f = Math.min(1, Math.max(0, fraction))
  const d = new Date(s + (e - s) * f)
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}

/** Положение даты или интервала на шкале в процентах (для адаптивной вёрстки без пикселей). */
export function pct(start, end, from, to = null) {
  const s = parseDate(start).getTime()
  const e = Math.max(parseDate(end).getTime(), s + DAY)
  const at = (v) => ((parseDate(v).getTime() - s) / (e - s)) * 100
  const left = Math.min(100, Math.max(0, at(from)))
  if (to === null) return { left }
  // факт по снимкам включает последний день целиком
  const right = Math.min(100, Math.max(0, at(to) + (DAY / (e - s)) * 100))
  return { left, width: Math.max(0.4, right - left) }
}

/** Попадает ли дата в диапазон шкалы. */
export function inRange(start, end, date) {
  const t = parseDate(date)?.getTime()
  return t !== undefined && t >= parseDate(start).getTime() && t <= parseDate(end).getTime()
}
