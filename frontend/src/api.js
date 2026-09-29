import { session, setSession } from './store.js'

export class ApiError extends Error {
  constructor(status, message) {
    super(message)
    this.status = status
  }
}

async function request(method, path, { json, form, query } = {}) {
  const url = new URL('/api' + path, window.location.origin)
  for (const [k, v] of Object.entries(query || {})) {
    if (v !== undefined && v !== null && v !== '') url.searchParams.set(k, v)
  }
  const headers = {}
  if (session.token) headers.Authorization = `Bearer ${session.token}`
  let body
  if (json !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(json)
  } else if (form) {
    body = form
  }
  let res
  try {
    res = await fetch(url, { method, headers, body })
  } catch {
    throw new ApiError(0, 'Сервер недоступен. Проверьте, что бэкенд запущен.')
  }
  if (res.status === 401 && session.token) {
    setSession(null)
    window.location.assign('/login')
  }
  if (res.status === 204) return null
  const text = await res.text()
  let data = null
  try { data = text ? JSON.parse(text) : null } catch { data = text }
  if (!res.ok) {
    let message = `Ошибка ${res.status}`
    if (data && typeof data.detail === 'string') message = data.detail
    else if (data && Array.isArray(data.detail)) message = data.detail.map((d) => d.msg).join('; ')
    throw new ApiError(res.status, message)
  }
  return data
}

function filesForm(files, fields = {}) {
  const form = new FormData()
  for (const f of files) form.append('files', f, f.name)
  for (const [k, v] of Object.entries(fields)) {
    if (v !== undefined && v !== null && v !== '') form.append(k, String(v))
  }
  return form
}

export const api = {
  register: (email, password, name) => request('POST', '/auth/register', { json: { email, password, name } }),
  login: (email, password) => request('POST', '/auth/login', { json: { email, password } }),
  me: () => request('GET', '/auth/me'),
  health: () => request('GET', '/health'),
  objectTypes: () => request('GET', '/object-types'),
  methodology: () => request('GET', '/methodology'),

  projects: () => request('GET', '/projects'),
  createProject: (data) => request('POST', '/projects', { json: data }),
  project: (id) => request('GET', `/projects/${id}`),
  updateProject: (id, data) => request('PATCH', `/projects/${id}`, { json: data }),
  deleteProject: (id) => request('DELETE', `/projects/${id}`),
  overview: (id) => request('GET', `/projects/${id}/overview`),
  geocodeProject: (id, force = false) => request('POST', `/projects/${id}/geocode`, { query: { force: force || undefined } }),
  placeProject: (id, lat, lon) => request('PATCH', `/projects/${id}`, { json: { lat, lon } }),

  createBuilding: (projectId, data) => request('POST', `/projects/${projectId}/buildings`, { json: data }),
  building: (id) => request('GET', `/buildings/${id}`),
  updateBuilding: (id, data) => request('PATCH', `/buildings/${id}`, { json: data }),
  deleteBuilding: (id) => request('DELETE', `/buildings/${id}`),

  plan: (id) => request('GET', `/buildings/${id}/plan`),
  updateTask: (buildingId, taskId, data) => request('PATCH', `/buildings/${buildingId}/plan/tasks/${taskId}`, { json: data }),
  bulkToggle: (buildingId, taskIds, enabled) =>
    request('POST', `/buildings/${buildingId}/plan/bulk`, { json: { task_ids: taskIds, enabled } }),
  reschedule: (id) => request('POST', `/buildings/${id}/plan/reschedule`),
  regenerate: (id) => request('POST', `/buildings/${id}/plan/regenerate`),

  photos: (buildingId, query) => request('GET', `/buildings/${buildingId}/photos`, { query }),
  uploadPhotos: (buildingId, files, fields) =>
    request('POST', `/buildings/${buildingId}/photos`, { form: filesForm(files, fields) }),
  photo: (id) => request('GET', `/photos/${id}`),
  updatePhoto: (id, data) => request('PATCH', `/photos/${id}`, { json: data }),
  replaceDetections: (id, items) => request('PUT', `/photos/${id}/detections`, { json: { items } }),
  redetect: (id) => request('POST', `/photos/${id}/redetect`),
  deletePhoto: (id) => request('DELETE', `/photos/${id}`),

  stages: (buildingId) => request('GET', `/buildings/${buildingId}/stages`),
  stage: (buildingId, phase) => request('GET', `/buildings/${buildingId}/stages/${encodeURIComponent(phase)}`),
  methodologyNorms: (objectType) => request('GET', '/methodology/norms', { query: { object_type: objectType } }),
  methodologyCalc: (kind, params) => request('POST', '/methodology/calc', { json: { kind, params } }),

  analysis: (buildingId, at) => request('GET', `/buildings/${buildingId}/analysis`, { query: { at } }),
  runAnalysis: (buildingId, at) => request('POST', `/buildings/${buildingId}/analysis`, { query: { at } }),
  timeline: (buildingId, at) => request('GET', `/buildings/${buildingId}/timeline`, { query: { at } }),
  history: (buildingId) => request('GET', `/buildings/${buildingId}/history`),
  deviations: (buildingId) => request('GET', `/buildings/${buildingId}/deviations`),
  reportLink: (projectId, ttlHours) => request('POST', `/projects/${projectId}/report-link`, { query: { ttl_hours: ttlHours } }),

  cameras: (projectId) => request('GET', `/projects/${projectId}/cameras`),
  createCamera: (projectId, data) => request('POST', `/projects/${projectId}/cameras`, { json: data }),
  updateCamera: (id, data) => request('PATCH', `/cameras/${id}`, { json: data }),
  deleteCamera: (id) => request('DELETE', `/cameras/${id}`),

  assistantDocuments: () => request('GET', '/assistant/documents'),
  addAssistantDocument: (file) => {
    const form = new FormData()
    form.append('file', file, file.name)
    return request('POST', '/assistant/documents', { form })
  },
  deleteAssistantDocument: (id) => request('DELETE', `/assistant/documents/${id}`),
}

/**
 * Вопрос помощнику с потоковым ответом (NDJSON: meta → delta… → done).
 * onMeta({ intent, sources, project }) вызывается один раз, onDelta(text) — на каждый фрагмент.
 */
export async function askAssistant(question, { projectId = null, signal, onMeta, onDelta } = {}) {
  const headers = { 'Content-Type': 'application/json' }
  if (session.token) headers.Authorization = `Bearer ${session.token}`
  let res
  try {
    res = await fetch('/api/assistant/chat', {
      method: 'POST', headers, signal, body: JSON.stringify({ question, project_id: projectId || null }),
    })
  } catch (e) {
    if (e.name === 'AbortError') throw e
    throw new ApiError(0, 'Сервер недоступен. Проверьте, что бэкенд запущен.')
  }
  if (res.status === 401 && session.token) {
    setSession(null)
    window.location.assign('/login')
  }
  if (!res.ok) {
    let message = `Ошибка ${res.status}`
    try {
      const data = await res.json()
      if (typeof data.detail === 'string') message = data.detail
    } catch { /* ответ не JSON */ }
    throw new ApiError(res.status, message)
  }
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  const handle = (line) => {
    if (!line.trim()) return
    const event = JSON.parse(line)
    if (event.type === 'meta') onMeta?.(event)
    else if (event.type === 'delta') onDelta?.(event.text)
  }
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let nl
    while ((nl = buffer.indexOf('\n')) >= 0) {
      handle(buffer.slice(0, nl))
      buffer = buffer.slice(nl + 1)
    }
  }
  handle(buffer + decoder.decode())
}

export function imageUrl(photoId, width) {
  const q = new URLSearchParams({ token: session.token || '' })
  if (width) q.set('w', width)
  return `/api/photos/${photoId}/image?${q}`
}

export function deviationsCsvUrl(buildingId) {
  return `/api/buildings/${buildingId}/deviations.csv?token=${encodeURIComponent(session.token || '')}`
}

export function reportUrl(projectId, at) {
  const q = new URLSearchParams({ token: session.token || '' })
  if (at) q.set('at', at)
  return `/api/projects/${projectId}/report.html?${q}`
}
