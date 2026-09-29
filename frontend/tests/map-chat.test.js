import test from 'node:test'
import assert from 'node:assert/strict'
import { escapeHtml, popupHtml, statusColor } from '../src/lib/map.js'
import { renderMarkdown } from '../src/lib/chat-format.js'

test('карточка стройки экранирует пользовательские строки', () => {
  const html = popupHtml({ id: 7, name: '<img src=x onerror=alert(1)>', address: 'Москва & «Север»', geo_source: 'approx' },
    { status: 'critical', actual: 34, planned: 41 })
  assert.ok(!html.includes('<img src=x'))
  assert.ok(html.includes('&lt;img src=x'))
  assert.ok(html.includes('Москва &amp; «Север»'))
  assert.ok(html.includes('data-open="7"'))
  assert.ok(html.includes('34%'))
  assert.ok(html.includes('приблизительно'))
})

test('неизвестный статус окрашивается серым', () => {
  assert.equal(statusColor('nope'), statusColor('unknown'))
  assert.equal(escapeHtml(null), '')
})

test('markdown помощника: списки, жирный, без HTML-инъекций', () => {
  const html = renderMarkdown('Итог:\n\n- **Иванов** — тел. 1\n- _демо_\n\n1. раз\n2. два\n\n<script>x</script>')
  assert.ok(html.includes('<ul><li><strong>Иванов</strong> — тел. 1</li><li><em>демо</em></li></ul>'))
  assert.ok(html.includes('<ol><li>раз</li><li>два</li></ol>'))
  assert.ok(html.includes('&lt;script&gt;'))
  assert.ok(!html.includes('<script>'))
})

test('незакрытый жирный во время потока не ломает разметку', () => {
  assert.equal(renderMarkdown('Идёт **ответ'), '<p>Идёт **ответ</p>')
})
