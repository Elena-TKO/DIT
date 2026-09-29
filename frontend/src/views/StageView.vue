<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { api, imageUrl } from '../api.js'
import { refreshNav, ui } from '../store.js'
import { countLabel, formatDate, formatDateTime, toLocalInput } from '../lib/format.js'
import Icon from '../components/Icon.vue'
import PhotoInspector from '../components/PhotoInspector.vue'
import StageCalc from '../components/StageCalc.vue'

// Страница одного этапа работ: все снимки этапа, анализ каждого (техника и её количество против норм),
// сводная сверка с нормативами, расчёт техники и дозагрузка снимков на этот этап.
const props = defineProps({ id: { type: Number, required: true }, phase: { type: String, required: true } })

const data = ref(null)
const building = ref(null)
const classes = ref([])
const error = ref('')
const openId = ref(null)
const files = ref([])
const takenAt = ref('')
const uploading = ref(false)
const uploadMsg = ref('')
const fileInput = ref(null)
const dragging = ref(false)

const STATE = {
  ok: { label: 'в норме', cls: 'ok' }, short: { label: 'меньше нормы', cls: 'warn' }, missing: { label: 'нет на снимках', cls: 'bad' },
  excess: { label: 'больше нормы', cls: 'warn' }, unexpected: { label: 'нетипична для этапа', cls: 'warn' },
}
const OBS = { high: 'хорошо видно камерами', medium: 'видно частично', low: 'видно слабо', none: 'камерами не видно' }
const range = (r) => (r.max_count === null || r.max_count === undefined ? `от ${r.min_count}` : r.min_count === r.max_count ? `${r.min_count}` : `${r.min_count}–${r.max_count}`)
const stage = computed(() => data.value?.stage || {})

async function load() {
  error.value = ''
  try {
    const [d, b] = await Promise.all([api.stage(props.id, props.phase), api.building(props.id)])
    data.value = d
    building.value = b
    Object.assign(ui, { projectId: b.project.id, buildingId: props.id })
    if (!takenAt.value) {
      takenAt.value = toLocalInput(d.stage.photo_end ? `${d.stage.photo_end}T12:00` : d.stage.start ? `${d.stage.start}T09:00` : undefined)
    }
  } catch (e) {
    error.value = e.message
  }
}

function pick(event) {
  dragging.value = false
  const list = [...(event.target.files || event.dataTransfer?.files || [])]
  files.value = list.filter((f) => ['image/jpeg', 'image/png', 'image/webp', 'image/bmp'].includes(f.type))
  uploadMsg.value = list.length !== files.value.length ? 'Часть файлов пропущена: подходят JPEG, PNG, WEBP, BMP.' : ''
}

async function upload() {
  if (!files.value.length) return
  uploading.value = true
  uploadMsg.value = ''
  try {
    const res = await api.uploadPhotos(props.id, files.value, { phase: props.phase, start_at: takenAt.value, interval_min: 30 })
    uploadMsg.value = `Загружено ${res.uploaded}` + (res.errors?.length ? `; ошибки: ${res.errors.map((e) => `${e.file} — ${e.error}`).join('; ')}` : '')
    files.value = []
    if (fileInput.value) fileInput.value.value = ''
    await load()
    refreshNav()
  } catch (e) {
    uploadMsg.value = e.message
  } finally {
    uploading.value = false
  }
}

async function movePhoto(photo, phase) {
  try {
    await api.updatePhoto(photo.id, { phase })
    await load()
  } catch (e) {
    error.value = e.message
  }
}

onMounted(() => {
  load()
  api.methodology().then((m) => { classes.value = (m.equipment || []).map((e) => e.cls) }).catch(() => {})
})
watch(() => [props.id, props.phase], () => { data.value = null; takenAt.value = ''; load() })
</script>

<template>
  <main class="stage-page">
    <p v-if="error" class="error" role="alert">{{ error }} <button class="btn small" type="button" @click="load">Повторить</button></p>
    <p v-else-if="!data" role="status">Загружаем этап…</p>
    <template v-if="data && building">
      <nav class="workspace-breadcrumbs sp-crumbs" aria-label="Путь к этапу">
        <RouterLink to="/">Стройки</RouterLink><span>/</span>
        <RouterLink :to="`/projects/${building.project.id}`">{{ building.project.name }}</RouterLink><span>/</span>
        <RouterLink :to="`/buildings/${id}/plan`">{{ building.name }} · план работ</RouterLink><span>/</span>
        <b>{{ data.name }}</b>
      </nav>

      <header class="sp-head">
        <div>
          <span class="sp-kicker">Этап работ<template v-if="stage.status_label"> · <i :style="{ background: stage.color }"></i>{{ stage.status_label }}</template></span>
          <h1>{{ data.name }}</h1>
          <p>
            План {{ stage.start ? `${formatDate(stage.start)} — ${formatDate(stage.end)}` : 'не задан' }}
            · факт по снимкам {{ stage.photo_start ? `${formatDate(stage.photo_start)} — ${formatDate(stage.photo_end)}` : 'нет' }}
            · {{ countLabel(data.photos.length, 'снимок', 'снимка', 'снимков') }} · {{ OBS[data.observability] }}
          </p>
        </div>
        <RouterLink :to="`/buildings/${id}/plan`" class="btn">← План работ</RouterLink>
      </header>

      <nav class="sp-chips" aria-label="Другие этапы">
        <RouterLink v-for="s in data.stages" :key="s.phase" :to="`/buildings/${id}/stages/${s.phase}`" :class="{ on: s.phase === phase }">
          {{ s.name }}<span v-if="s.photos">{{ s.photos }}</span>
        </RouterLink>
      </nav>

      <div class="sp-grid">
        <section class="sp-panel sp-photos">
          <div class="sp-panel-head"><h2>Снимки этапа</h2><span>{{ data.photos.length }}</span></div>
          <form class="sp-upload" :class="{ over: dragging }" @submit.prevent="upload" @dragover.prevent="dragging = true"
            @dragleave="dragging = false" @drop.prevent="pick">
            <input ref="fileInput" type="file" multiple hidden accept="image/jpeg,image/png,image/webp,image/bmp" @change="pick" />
            <button type="button" class="sp-drop" :disabled="uploading" @click="fileInput.click()">
              <Icon name="upload" />{{ files.length ? `Выбрано: ${files.length}` : 'Добавить снимки на этот этап — выберите или перетащите файлы' }}
            </button>
            <label class="sp-time">Время первого снимка<input v-model="takenAt" type="datetime-local" :disabled="uploading" /></label>
            <button class="btn primary" type="submit" :disabled="uploading || !files.length">{{ uploading ? 'Распознаём технику…' : 'Загрузить и проанализировать' }}</button>
            <p v-if="uploadMsg" class="sp-msg">{{ uploadMsg }}</p>
          </form>

          <p v-if="!data.photos.length" class="sp-empty">На этот этап ещё нет снимков. Загрузите их выше или в разделе «Фото и техника» — этап определится по технике автоматически.</p>
          <ul v-else class="sp-list">
            <li v-for="p in data.photos" :key="p.id" class="sp-card">
              <button type="button" class="sp-img" @click="openId = p.id">
                <img :src="imageUrl(p.id, 640)" :alt="`Снимок от ${formatDateTime(p.taken_at)}`" loading="lazy" />
                <span class="sp-time-tag">{{ formatDateTime(p.taken_at) }}</span>
              </button>
              <div class="sp-body">
                <div class="sp-meta">
                  <span>{{ p.camera_name || 'без камеры' }}</span>
                  <span :class="p.phase_source === 'manual' ? 'sp-src manual' : 'sp-src'">{{ p.phase_source === 'manual' ? 'загружен на этап' : 'этап определён по технике' }}</span>
                </div>
                <p v-if="p.mismatch" class="sp-mismatch"><Icon name="alert" />По технике похоже на «{{ p.auto_phase_name }}»</p>
                <p v-else-if="p.phase_source === 'auto' && !p.phase_confirmed" class="sp-approx">Примерный этап: обязательная техника видна не полностью</p>
                <div class="sp-tags">
                  <span v-for="e in p.equipment" :key="e.cls" class="sp-tag">{{ e.label }} × {{ e.count }}</span>
                  <span v-if="!p.equipment.length" class="sp-none">техника не найдена</span>
                </div>
                <ul class="sp-check">
                  <li v-for="(c, i) in p.check" :key="i" :class="STATE[c.state].cls">
                    {{ c.labels.join(' / ') }}: {{ c.seen }}<template v-if="c.role !== 'unexpected'"> (норма {{ range({ min_count: c.min_count, max_count: c.max_count }) }})</template> — {{ STATE[c.state].label }}
                  </li>
                </ul>
                <label class="sp-move">Этап снимка
                  <select :value="p.phase_source === 'manual' ? p.phase : ''" @change="movePhoto(p, $event.target.value)">
                    <option value="">Авто: {{ p.auto_phase_name || 'не определён' }}</option>
                    <option v-for="s in data.stages" :key="s.phase" :value="s.phase">{{ s.name }}</option>
                  </select>
                </label>
              </div>
            </li>
          </ul>
        </section>

        <aside class="sp-side">
          <section class="sp-panel">
            <div class="sp-panel-head"><h2>Нужная техника</h2></div>
            <p class="sp-rule">{{ data.rule || data.hint }}</p>
            <table class="sp-table">
              <thead><tr><th>Техника</th><th>Норма</th><th>Макс. на кадре</th><th></th></tr></thead>
              <tbody>
                <tr v-for="c in data.check" :key="c.labels.join()" :class="STATE[c.state].cls">
                  <td>{{ c.labels.join(' или ') }}<small v-if="c.role !== 'required'"> · {{ c.role === 'typical' ? 'типичная' : 'нетипичная' }}</small></td>
                  <td>{{ c.role === 'unexpected' ? '—' : range({ min_count: c.min_count, max_count: c.max_count }) }}</td>
                  <td>{{ c.seen }}</td>
                  <td class="sp-state">{{ STATE[c.state].label }}</td>
                </tr>
                <tr v-if="!data.requirements.length"><td colspan="4" class="sp-none">Для этапа техника не нормируется.</td></tr>
              </tbody>
            </table>
            <h3>Нормативная база</h3>
            <ul class="sp-docs"><li v-for="d in data.docs" :key="d">{{ d }}</li></ul>
          </section>
          <section v-if="data.calc" class="sp-panel"><StageCalc :kind="data.calc" /></section>
        </aside>
      </div>

      <PhotoInspector v-if="openId" :photo-id="openId" :classes="classes" @close="openId = null" @changed="load" />
    </template>
  </main>
</template>

<style>
.stage-page { padding: 24px 40px 60px; max-width: 1500px; margin: auto; }
.sp-crumbs { margin-bottom: 16px; }
.sp-head { display: flex; justify-content: space-between; align-items: flex-end; gap: 24px; margin-bottom: 18px; }
.sp-kicker { display: inline-flex; align-items: center; gap: 6px; font-size: 11px; font-weight: 700; text-transform: uppercase; color: var(--ink-3); }
.sp-kicker i { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
.sp-head h1 { font-family: var(--serif); font-size: 44px; font-weight: 400; line-height: 1.1; margin: 6px 0 8px; }
.sp-head p { margin: 0; color: var(--ink-3); font-size: 13px; }
.sp-chips { display: flex; gap: 8px; overflow-x: auto; padding-bottom: 6px; margin-bottom: 22px; }
.sp-chips a { flex: none; display: inline-flex; gap: 6px; align-items: center; padding: 6px 12px; border-radius: 999px; border: 1px solid var(--hair-2); font-size: 12px; text-decoration: none; color: var(--ink); white-space: nowrap; }
.sp-chips a span { font-size: 10px; font-weight: 700; padding: 0 6px; border-radius: 999px; background: var(--accent); color: var(--accent-ink); }
.sp-chips a.on { background: var(--accent); color: var(--accent-ink); border-color: var(--accent); }
.sp-chips a.on span { background: var(--accent-ink); color: var(--accent); }
.sp-grid { display: grid; grid-template-columns: minmax(0, 1.7fr) minmax(320px, 1fr); gap: 24px; align-items: start; }
.sp-side { display: grid; gap: 24px; }
.sp-panel { background: var(--panel); border: 1px solid var(--hair); border-radius: 18px; padding: 22px; min-width: 0; }
.sp-panel-head { display: flex; align-items: baseline; justify-content: space-between; margin-bottom: 14px; }
.sp-panel-head h2 { font-family: var(--serif); font-size: 26px; font-weight: 400; }
.sp-panel-head span { color: var(--ink-3); font-size: 13px; }
.sp-panel h3 { font-size: 11px; text-transform: uppercase; color: var(--ink-3); margin: 18px 0 8px; }
.sp-upload { display: grid; grid-template-columns: 1fr auto auto; gap: 12px; align-items: end; padding: 14px; border: 1.5px dashed var(--hair-2); border-radius: 14px; margin-bottom: 18px; }
.sp-upload.over { border-color: var(--accent); }
.sp-drop { display: flex; align-items: center; gap: 8px; background: none; border: 0; font: inherit; font-size: 13px; color: var(--accent); cursor: pointer; text-align: left; padding: 8px 0; }
.sp-drop svg { width: 18px; height: 18px; flex: none; }
.sp-time { display: grid; gap: 4px; font-size: 11px; color: var(--ink-3); }
.sp-time input { font: inherit; font-size: 12px; padding: 7px 9px; }
.sp-msg { grid-column: 1 / -1; margin: 0; font-size: 12px; color: var(--ink-3); }
.sp-empty, .sp-none { color: var(--ink-3); font-size: 13px; }
.sp-list { list-style: none; margin: 0; padding: 0; display: grid; gap: 16px; }
.sp-card { display: grid; grid-template-columns: 260px minmax(0, 1fr); gap: 18px; padding-top: 16px; border-top: 1px solid var(--hair); }
.sp-card:first-child { border-top: 0; padding-top: 0; }
.sp-img { position: relative; padding: 0; border: 0; background: var(--panel-2); border-radius: 12px; overflow: hidden; aspect-ratio: 4 / 3; cursor: zoom-in; }
.sp-img img { width: 100%; height: 100%; object-fit: cover; display: block; }
.sp-time-tag { position: absolute; left: 8px; bottom: 8px; font-size: 11px; padding: 3px 9px; border-radius: 999px; background: rgba(10, 14, 16, 0.6); color: #fff; }
.sp-body { display: grid; gap: 8px; align-content: start; min-width: 0; }
.sp-meta { display: flex; gap: 10px; flex-wrap: wrap; font-size: 12px; color: var(--ink-3); }
.sp-src { padding: 1px 8px; border-radius: 999px; border: 1px solid var(--hair-2); }
.sp-src.manual { border-color: var(--accent); color: var(--accent); }
.sp-mismatch, .sp-approx { display: flex; align-items: center; gap: 6px; margin: 0; font-size: 12px; color: var(--warning); }
.sp-mismatch svg { width: 14px; height: 14px; }
.sp-approx { color: var(--ink-3); }
.sp-tags { display: flex; flex-wrap: wrap; gap: 6px; }
.sp-tag { font-size: 12px; padding: 2px 9px; border-radius: 999px; background: var(--panel-2); border: 1px solid var(--hair); }
.sp-check { list-style: none; margin: 0; padding: 0; display: grid; gap: 3px; font-size: 12px; }
.sp-check li::before { content: "● "; }
.sp-check .ok, .sp-table .ok .sp-state { color: var(--ok); }
.sp-check .warn, .sp-table .warn .sp-state { color: var(--warning); }
.sp-check .bad, .sp-table .bad .sp-state { color: var(--critical); }
.sp-move { display: flex; gap: 8px; align-items: center; font-size: 11px; color: var(--ink-3); }
.sp-move select { font: inherit; font-size: 12px; padding: 4px 8px; max-width: 280px; }
.sp-rule { margin: 0 0 12px; font-size: 13px; line-height: 1.5; }
.sp-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.sp-table th { text-align: left; font-size: 10px; text-transform: uppercase; color: var(--ink-3); padding: 6px; border-bottom: 1px solid var(--hair-2); }
.sp-table td { padding: 7px 6px; border-bottom: 1px solid var(--hair); }
.sp-table small { color: var(--ink-3); }
.sp-state { white-space: nowrap; font-weight: 600; }
.sp-docs { margin: 0; padding-left: 18px; font-size: 12px; display: grid; gap: 4px; }
@media (max-width: 1100px) { .sp-grid { grid-template-columns: 1fr; } }
@media (max-width: 760px) { .stage-page { padding: 20px 16px 40px; } .sp-card { grid-template-columns: 1fr; } .sp-upload { grid-template-columns: 1fr; } .sp-head { flex-direction: column; align-items: flex-start; } .sp-head h1 { font-size: 32px; } }
</style>
