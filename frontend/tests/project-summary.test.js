import { test } from 'node:test'
import assert from 'node:assert/strict'
import { projectSummary } from '../src/lib/project-summary.js'
const object = { photos: 2, completion_percent: 50, planned_percent: 60, forecast_end: '2026-12-18', status: 'ok' }
test('empty projects do not invent progress or forecasts', () => {
  assert.deepEqual(projectSummary([]), { actual: null, planned: null, forecast: null, status: 'unknown' })
})
test('averages progress and takes latest forecast and worst status', () => {
  assert.deepEqual(projectSummary([object, { ...object, completion_percent: 70, forecast_end: '2027-01-10', status: 'warning' }]), { actual: 60, planned: 60, forecast: '2027-01-10', status: 'warning' })
})
test('missing observations and null values stay unknown instead of zero', () => {
  const result = projectSummary([object, { ...object, photos: 0, planned_percent: null }])
  assert.equal(result.actual, null)
  assert.equal(result.planned, null)
  assert.equal(result.forecast, null)
  assert.equal(result.status, 'unknown')
})
test('known critical issue remains visible when other data is missing', () => {
  assert.equal(projectSummary([{ ...object, status: 'critical' }, { photos: 0 }]).status, 'critical')
})
