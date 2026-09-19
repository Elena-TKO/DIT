import { test } from 'node:test'
import assert from 'node:assert/strict'
import { parseDate, formatDate, formatDateTime, toLocalInput, plural, countLabel } from '../src/lib/format.js'
import { makeScale, monthTicks, bar } from '../src/lib/gantt.js'
import { classColor, timelineColor, TIMELINE_COLORS } from '../src/lib/labels.js'

test('даты разбираются без сдвига часового пояса', () => {
  const d = parseDate('2025-05-03')
  assert.equal(d.getDate(), 3)
  assert.equal(d.getMonth(), 4)
  assert.equal(formatDate('2025-05-03'), '3 мая 2025')
  assert.equal(formatDateTime('2025-05-03T08:05:00'), '3 мая 2025, 08:05')
  assert.equal(toLocalInput('2025-12-31T23:59'), '2025-12-31T23:59')
  assert.equal(formatDate(null), '—')
})

test('склонение числительных', () => {
  assert.equal(plural(1, 'снимок', 'снимка', 'снимков'), 'снимок')
  assert.equal(plural(3, 'снимок', 'снимка', 'снимков'), 'снимка')
  assert.equal(plural(11, 'снимок', 'снимка', 'снимков'), 'снимков')
  assert.equal(countLabel(22, 'снимок', 'снимка', 'снимков'), '22 снимка')
})

test('шкала и полосы Ганта', () => {
  const s = makeScale('2025-01-01', '2025-01-11', 1000)
  assert.equal(s.x('2025-01-01'), 0)
  assert.equal(s.x('2025-01-06'), 500)
  assert.equal(s.x('2025-01-11'), 1000)
  assert.deepEqual(bar(s, '2024-12-20', '2025-01-06'), { x: 0, w: 500 })
  assert.equal(bar(s, '2025-01-05', '2025-01-05').w, 2)
})

test('метки месяцев не наезжают', () => {
  const ticks = monthTicks('2025-01-15', '2026-12-31', 300, 44)
  assert.equal(ticks.length, 23)
  const xs = ticks.filter((t) => t.label).map((t) => t.x).sort((a, b) => a - b)
  for (let i = 1; i < xs.length; i++) assert.ok(xs[i] - xs[i - 1] >= 44)
  assert.ok(ticks.some((t) => t.label === '2026'))
})

test('цвет класса стабилен', () => {
  const classes = ['excavator', 'dump_truck']
  assert.equal(classColor('dump_truck', classes), classColor('dump_truck', classes))
  assert.notEqual(classColor('excavator', classes), classColor('dump_truck', classes))
})

test('статусы таймлайна имеют цвета тёмной темы', () => {
  for (const key of ['planned', 'awaiting', 'on_track', 'at_risk', 'delayed', 'done', 'ahead', 'unobservable', 'unconfirmed']) {
    assert.match(TIMELINE_COLORS[key], /^#[0-9A-F]{6}$/i, key)
  }
  assert.equal(timelineColor('unknown', '#123456'), '#123456')
  assert.notEqual(timelineColor('delayed'), timelineColor('at_risk'))
})
