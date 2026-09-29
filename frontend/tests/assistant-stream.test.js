import test from 'node:test'
import assert from 'node:assert/strict'
import http from 'node:http'
import { register } from 'node:module'

register(new URL('./support/vue-stub.mjs', import.meta.url))
globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} }
globalThis.window = { location: { origin: 'http://localhost', assign() {} } }

const ANSWER = 'Ответственный за экскаваторы — **Иванов И. И.**, тел. +7 (999) 000-10-01.\n\n- диспетчерская — круглосуточно'
const lines = [
  JSON.stringify({ type: 'meta', intent: 'contacts', sources: [{ doc_id: 'kb-contacts', title: 'Контакты', snippet: '…' }] }),
  ...ANSWER.match(/\S+\s*|\s+/g).map((text) => JSON.stringify({ type: 'delta', text })),
  JSON.stringify({ type: 'done' }),
].join('\n') + '\n'

test('поток ответа помощника собирается при любых границах чанков, ошибки API разбираются', async () => {
  const body = Buffer.from(lines)
  const server = http.createServer(async (req, res) => {
    let raw = ''
    for await (const c of req) raw += c
    const { question } = JSON.parse(raw)
    if (!question.trim()) {
      res.writeHead(422, { 'Content-Type': 'application/json' })
      return res.end(JSON.stringify({ detail: 'Введите вопрос' }))
    }
    res.writeHead(200, { 'Content-Type': 'application/x-ndjson' })
    // куски по 5 байт: разрезают строки NDJSON и многобайтовые символы кириллицы
    for (let i = 0; i < body.length; i += 5) {
      res.write(body.subarray(i, i + 5))
      await new Promise((r) => setImmediate(r))
    }
    res.end()
  }).listen(0)
  const realFetch = globalThis.fetch
  globalThis.fetch = (url, opts) => realFetch(`http://127.0.0.1:${server.address().port}${url}`, opts)
  try {
    const { askAssistant, ApiError } = await import('../src/api.js')
    let text = ''
    let meta = null
    await askAssistant('не хватает экскаваторов', { onMeta: (m) => { meta = m }, onDelta: (t) => { text += t } })
    assert.equal(text, ANSWER)
    assert.equal(meta.intent, 'contacts')
    await assert.rejects(askAssistant(' '), (e) => e instanceof ApiError && e.status === 422 && e.message === 'Введите вопрос')
  } finally {
    globalThis.fetch = realFetch
    server.close()
  }
})
