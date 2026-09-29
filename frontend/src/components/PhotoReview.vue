<script setup>
import { computed, onMounted, onBeforeUnmount, ref } from 'vue'
import { api, imageUrl } from '../api.js'
import { formatDateTime, toLocalInput } from '../lib/format.js'
import { ACTIVITY, VERDICT_STATUS, SEVERITY } from '../lib/labels.js'
import Icon from './Icon.vue'
const props = defineProps({ building: { type: Object, required: true } })
const emit = defineEmits(['changed'])
const photo = ref(null)
const result = ref(null)
const files = ref([])
const fileInput = ref(null)
const preview = ref('')
const busy = ref(false)
const loading = ref(true)
const error = ref('')
const step = ref('')
const saved = ref(false)
const cameraId = ref('')
const cameras = ref([])
const takenAt = ref(toLocalInput())
let alive = true
const verdict = computed(() => result.value?.verdict)
const observed = computed(() => Boolean(verdict.value?.observed))
const deviations = computed(() => observed.value ? verdict.value?.deviations || [] : [])
const recommendations = computed(() => observed.value ? result.value?.recommendations || [] : [])
const detections = computed(() => preview.value ? [] : (photo.value?.detections || []).filter(d => Array.isArray(d.bbox) && d.confidence >= (photo.value.min_confidence ?? 0)))
const requirements = computed(() => (verdict.value?.checklist || []).flatMap(c => c.required || []))
const priority = { high: 'Срочно', medium: 'Важно', low: 'К сведению' }
function clearPreview() { if (preview.value) URL.revokeObjectURL(preview.value); preview.value = '' }
function pick(event) {
  if (busy.value) return
  clearPreview()
  const selected = [...(event.target.files || event.dataTransfer?.files || [])]
  if (selected.some(f => !['image/jpeg','image/png','image/webp','image/bmp'].includes(f.type) || f.size > 25 * 1024 * 1024)) {
    error.value = 'Выберите JPEG, PNG, WEBP или BMP размером до 25 МБ.'; files.value = []; return
  }
  files.value = selected.slice(0,1)
  error.value = ''
  if (files.value[0]) { preview.value = URL.createObjectURL(files.value[0]); result.value = null; saved.value = false }
}
async function load() {
  loading.value = true
  error.value = ''
  try {
    const list = await api.photos(props.building.id, { limit: 1, offset: 0 })
    if (!alive) return
    photo.value = list.items?.length ? await api.photo(list.items[0].id) : null
    if (photo.value) result.value = await api.analysis(props.building.id)
  } catch(e) { if (alive) error.value = e.message }
  finally { if (alive) loading.value = false }
}
async function analyze() {
  if (busy.value) return
  busy.value = true; error.value = ''; saved.value = false; result.value = null
  try {
    if (files.value.length) {
      step.value = 'Загружаем снимок и распознаём технику…'
      const uploaded = await api.uploadPhotos(props.building.id, files.value, { camera_id: cameraId.value, start_at: takenAt.value, interval_min: 0 })
      if (uploaded.errors?.length) throw new Error(uploaded.errors.map(e => typeof e === 'string' ? e : e.error || e.message || 'Не удалось загрузить снимок').join('; '))
      files.value = []; clearPreview(); if (fileInput.value) fileInput.value.value = ''
      const list = await api.photos(props.building.id, { limit: 1, offset: 0 })
      photo.value = list.items?.length ? await api.photo(list.items[0].id) : null
      emit('changed')
    }
    step.value = 'Сопоставляем технику с планом работ…'
    const data = await api.analysis(props.building.id)
    if (alive) result.value = data
  } catch(e) { if (alive) error.value = e.message }
  finally { if (alive) { busy.value = false; step.value = '' } }
}
async function save() {
  if (busy.value) return
  busy.value = true; error.value = ''
  try { result.value = await api.runAnalysis(props.building.id, result.value?.at); saved.value = true; emit('changed') }
  catch(e) { error.value = e.message }
  finally { busy.value = false }
}
onMounted(() => {
  load()
  api.cameras(props.building.project_id || props.building.project.id).then(data => {
    if (alive) cameras.value = data.filter(c => !c.building_id || c.building_id === props.building.id)
  }).catch(() => {})
})
onBeforeUnmount(() => { alive = false; clearPreview() })
</script>
<template>
  <section class="photo-workflow" :aria-busy="busy || loading">
    <header class="review-heading"><div><h1>Фото и отклонения</h1><p>{{ photo && !preview ? 'Кадр ' + formatDateTime(photo.taken_at) + ' · ' + (photo.camera_name || 'Без камеры') : building.name + ' · Загрузите снимок для анализа техники' }}</p></div><RouterLink :to="`/buildings/${building.id}/plan`" class="btn">План работ →</RouterLink></header>
    <p v-if="error" class="error" role="alert">{{ error }} <button v-if="!photo && !preview" class="btn small" @click="load">Повторить</button></p>
    <p v-if="loading" class="review-notice" role="status">Загружаем снимки…</p>
    <div class="review-top">
      <section class="photo-surface">
        <div class="surface-head"><span>{{ preview ? 'НОВЫЙ СНИМОК' : photo?.camera_name || 'СНИМОК ОБЪЕКТА' }}<RouterLink v-if="photo?.phase && !preview" :to="`/buildings/${building.id}/stages/${photo.phase}`" class="review-stage-link">Этап: {{ photo.phase_source === 'auto' && !photo.phase_confirmed ? '≈ ' : '' }}{{ photo.phase_name }} →</RouterLink></span><button v-if="photo || preview" class="text-action" :disabled="busy" @click="fileInput.click()">Заменить фото</button></div>
        <input ref="fileInput" type="file" accept="image/jpeg,image/png,image/webp,image/bmp" hidden @change="pick" />
        <div v-if="photo || preview" class="review-image"><img :src="preview || imageUrl(photo.id, 1400)" alt="Снимок строительной площадки" /><div v-for="(d,i) in detections" :key="d.id || i" class="detection-frame" :class="d.activity || 'unknown'" :style="{ left:d.bbox[0]*100+'%', top:d.bbox[1]*100+'%', width:(d.bbox[2]-d.bbox[0])*100+'%', height:(d.bbox[3]-d.bbox[1])*100+'%' }"><span>{{ d.label || d.cls }} · {{ ACTIVITY[d.activity] || 'обнаружено' }} {{ Math.round(d.confidence*100) }}%</span></div></div>
        <div v-else class="photo-drop" @dragover.prevent @drop.prevent="pick"><Icon name="upload" /><h3>Фото ещё не загружено</h3><p>Добавьте снимок с камеры, чтобы получить<br />анализ техники и отклонений</p><button class="btn primary" :disabled="busy || loading" @click="fileInput.click()">Загрузить фото</button></div>
        <form v-if="preview" class="review-upload" @submit.prevent="analyze"><label class="field">Камера<select v-model="cameraId" :disabled="busy"><option value="">Без камеры</option><option v-for="c in cameras" :key="c.id" :value="c.id">{{ c.name }}</option></select></label><label class="field">Время съёмки<input v-model="takenAt" type="datetime-local" required :disabled="busy" /></label><button class="btn primary" :disabled="busy">Анализировать фото</button><p>Без серии кадров одной камеры длительность простоя не определяется.</p></form>
        <div v-if="busy" class="analysis-wait" role="status"><span class="review-spinner"></span>{{ step || 'Сохраняем вердикт…' }}</div>
        <button v-if="photo && !preview && !busy && !observed" class="btn primary retry-analysis" @click="analyze">Получить анализ</button>
      </section>
      <section class="review-panel verdict-panel"><h2>Вердикт</h2><template v-if="observed && !busy"><span class="review-status" :class="verdict.status">{{ VERDICT_STATUS[verdict.status]?.label || 'Результат анализа' }}</span><span class="review-label">Фактический этап</span><h3 class="stage-name">{{ verdict.stage?.top_name || 'Не определён' }}</h3><span class="review-label">По методике требуется</span><ul class="requirement-list"><li v-for="(r,i) in requirements" :key="i" :class="r.present ? 'ok' : 'warning'">{{ (r.labels || r.seen || []).join(' или ') }} <span>{{ r.present ? '✓' : 'не обнаружено' }}</span></li></ul><p v-if="!requirements.length" class="muted">Нет требований на выбранную дату.</p><span class="review-label">Нарушения</span><p v-for="(d,i) in deviations.slice(0,3)" :key="i" class="violation" :class="d.severity">{{ d.title }}</p><p v-if="!deviations.length" class="ok">Отклонений не выявлено</p><p class="review-caption">{{ verdict.summary }}</p></template><div v-else class="review-empty"><Icon :name="busy ? 'clock' : 'report'" /><h3>{{ busy ? 'Идёт анализ' : 'Нет данных для анализа' }}</h3><p>{{ busy ? 'Результат появится после ответа сервера.' : 'Вердикт, требуемая техника и нарушения появятся после анализа фото.' }}</p></div></section>
    </div>
    <div class="review-bottom"><section class="review-panel"><div class="section-heading"><h2>Отклонения</h2><span v-if="observed">{{ deviations.length }}</span></div><div v-if="!observed || busy" class="review-empty"><Icon name="alert" /><h3>Отклонения ещё не определены</h3><p>Загрузите фото и запустите анализ.</p></div><p v-else-if="!deviations.length" class="review-notice">Отклонений не выявлено.</p><article v-for="(d,i) in deviations" v-else :key="i" class="deviation-item"><span class="review-badge" :class="d.severity">{{ SEVERITY[d.severity] || d.severity }}</span><h3>{{ d.title }}</h3><p>{{ d.message }}</p><small>{{ (d.zones || []).join(' · ') }}</small></article></section><section class="review-panel"><h2>Рекомендации</h2><div v-if="!observed || busy" class="review-empty"><Icon name="check" /><h3>Рекомендации появятся после анализа</h3><p>Загрузите фото, чтобы получить рекомендации по технике и организации работ.</p></div><ol v-else class="recommendation-list"><li v-for="(r,i) in recommendations" :key="i"><span class="review-badge" :class="r.priority">{{ priority[r.priority] || r.priority }}</span><p>{{ r.text }}</p></li><li v-if="!recommendations.length">Дополнительных рекомендаций нет.</li></ol><button v-if="observed" class="btn primary full-width" :disabled="busy || saved" @click="save">{{ saved ? 'Вердикт записан в журнал' : 'Записать вердикт в журнал' }}</button><button v-else class="btn primary full-width" :disabled="busy || loading" @click="fileInput.click()">Загрузить фото</button></section></div>
    <div v-if="observed" class="review-next"><span>Следующий шаг — сопоставить результат с календарным планом</span><RouterLink :to="`/buildings/${building.id}/plan`" class="btn primary">К анализу с таблицей →</RouterLink></div>
  </section>
</template>

<style>
.review-stage-link { margin-left: 12px; color: #356df3; text-decoration: none; text-transform: none; font-weight: 600; }
.design-classic .review-stage-link { color: var(--accent); }
</style>
