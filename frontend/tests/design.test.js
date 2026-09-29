import test from 'node:test'
import assert from 'node:assert/strict'
import { register } from 'node:module'

register(new URL('./support/vue-stub.mjs', import.meta.url))
const stored = { 'sk-design': 'classic' }
globalThis.localStorage = {
  getItem: (k) => stored[k] ?? null,
  setItem: (k, v) => { stored[k] = String(v) },
  removeItem: (k) => { delete stored[k] },
}

test('дизайн восстанавливается из браузера, переключается и запоминается', async () => {
  const { ui, setDesign, DESIGNS } = await import('../src/store.js')
  assert.deepEqual(DESIGNS.map((d) => d.key), ['light', 'classic'])
  assert.equal(ui.design, 'classic')
  setDesign('light')
  assert.equal(ui.design, 'light')
  assert.equal(stored['sk-design'], 'light')
  setDesign('neon')                 // неизвестное значение игнорируется
  assert.equal(ui.design, 'light')
})
