<script setup>
import { computed, onMounted, ref } from 'vue'
import { api, imageUrl } from '../api.js'
import { formatDateTime, toLocalInput, countLabel } from '../lib/format.js'
import CameraPanel from './CameraPanel.vue'
import Icon from './Icon.vue'
import PhotoCompare from './PhotoCompare.vue'
import PhotoInspector from './PhotoInspector.vue'

const props = defineProps({
  building: { type: Object, required: true },
  classes: { type: Array, default: () => [] },
  equipment: { type: Array, default: () => [] },
})
const emit = defineEmits(['changed'])

const PAGE = 60
const photos = ref([])
const total = ref(0)
const cameras = ref([])
const files = ref([])
const cameraId = ref('')
const startAt = ref(toLocalInput())
const interval = ref(30)
const timeMode = ref('series')   // 'single' — все снимки одним моментом, 'series' — с интервалом
const progress = ref(null)
const errors = ref([])
const error = ref('')
const openId = ref(null)
const dragging = ref(false)
const filters = ref({ camera_id: '', cls: '', taken_from: '', taken_to: '' })
const compare = ref([])
const fileInput = ref(null)

const uploadCameras = computed(() => cameras.value.filter((c) => !c.building_id || c.building_id === props.building.id))

async function loadPhotos(append = false) {
  try {
    const res = await api.photos(props.building.id, {
      limit: PAGE, offset: append ? photos.value.length : 0, ...filters.value,
    })
    photos.value = append ? [...photos.value, ...res.items] : res.items
    total.value = res.total
    if (!append && res.items.length) {
      // следующая загрузка по умолчанию продолжает ленту
      const last = new Date(res.items[0].taken_at)
      startAt.value = toLocalInput(new Date(last.getTime() + interval.value * 60000))
    }
  } catch (e) {
    error.value = e.message
  }
}

async function loadCameras() {
  cameras.value = await api.cameras(props.building.project_id).catch(() => [])
  if (!cameraId.value && uploadCameras.value.length === 1) cameraId.value = String(uploadCameras.value[0].id)
  if (!cameraId.value) timeMode.value = 'single'
}

function pick(event) {
  files.value = [...event.target.files]
}

function drop(event) {
  dragging.value = false
  files.value = [...event.dataTransfer.files].filter((f) => f.type.startsWith('image/'))
}

async function upload() {
  if (!files.value.length) return
  errors.value = []
  error.value = ''
  const batch = 3
  const list = files.value
  const base = new Date(startAt.value)
  const step = timeMode.value === 'series' ? interval.value : 0   // «одним моментом» = интервал 0
  progress.value = { done: 0, total: list.length }
  try {
    for (let i = 0; i < list.length; i += batch) {
      const chunkStart = new Date(base.getTime() + i * step * 60000)
      const res = await api.uploadPhotos(props.building.id, list.slice(i, i + batch), {
        camera_id: cameraId.value, start_at: toLocalInput(chunkStart), interval_min: step,
      })
      errors.value.push(...res.errors)
      progress.value = { done: Math.min(list.length, i + batch), total: list.length }
    }
    files.value = []
    await loadPhotos()
    emit('changed')
  } catch (e) {
    error.value = e.message
  } finally {
    progress.value = null
  }
}

function toggleCompare(id) {
  const next = compare.value.filter((x) => x !== id)
  compare.value = next.length === compare.value.length ? [...next, id].slice(-2) : next
}

function onCamerasChanged() {
  loadPhotos()
  loadCameras()
  emit('changed')
}

onMounted(() => {
  loadPhotos()
  loadCameras()
})
</script>

<template>
  <section class="stack">
    <form class="panel" @submit.prevent="upload">
      <div class="panel-head">
        <div>
          <h2>Загрузка снимков</h2>
          <p class="muted small">У снимков нет времени съёмки: первый получает указанный момент, каждый следующий — плюс интервал, в порядке выбора.</p>
        </div>
      </div>
      <div class="upload">
        <div class="drop" :class="{ over: dragging, filled: files.length }" role="button" tabindex="0"
          @click="fileInput.click()" @keydown.enter.prevent="fileInput.click()"
          @dragover.prevent="dragging = true" @dragleave="dragging = false" @drop.prevent="drop">
          <input ref="fileInput" type="file" accept="image/jpeg,image/png,image/webp,image/bmp" multiple hidden @change="pick" />
          <span class="drop-icon"><Icon :name="files.length ? 'image' : 'upload'" /></span>
          <b v-if="files.length">{{ countLabel(files.length, 'снимок выбран', 'снимка выбрано', 'снимков выбрано') }}</b>
          <b v-else>Перетащите снимки или выберите файлы</b>
          <span class="faint small">JPEG, PNG, WEBP до 25 МБ</span>
        </div>
        <div class="upload-fields">
          <label class="field">Камера
            <select v-model="cameraId">
              <option value="">Без камеры</option>
              <option v-for="c in uploadCameras" :key="c.id" :value="String(c.id)">{{ c.name }}{{ c.zone ? `, ${c.zone}` : '' }}</option>
            </select></label>
          <label class="field">{{ timeMode === 'series' ? 'Время первого снимка' : 'Время съёмки' }}
            <input v-model="startAt" type="datetime-local" required /></label>
          <div class="mode">
            <button type="button" :class="{ on: timeMode === 'single' }" @click="timeMode = 'single'">Одним моментом</button>
            <button type="button" :class="{ on: timeMode === 'series' }" @click="timeMode = 'series'">Серия с интервалом</button>
          </div>
          <label v-if="timeMode === 'series'" class="field">Интервал между снимками, мин
            <input v-model.number="interval" type="number" min="1" max="1440" /></label>
          <button class="btn primary" type="submit" :disabled="!files.length || progress">
            {{ progress ? `Распознаётся ${progress.done} из ${progress.total}` : 'Загрузить и распознать' }}
          </button>
          <div v-if="progress" class="progress" aria-live="polite"><i :style="{ width: (progress.done / progress.total) * 100 + '%' }"></i></div>
          <p v-if="!cameraId" class="small warn-hint">
        Камера не выбрана: снимки попадут в анализ этапа, но простой техники и потери в рублях по ним
        не считаются — для этого нужны последовательные кадры одной камеры.
      </p>
      <p v-else-if="timeMode === 'single'" class="faint small">
        Все снимки получат одно время съёмки — подходит для разовой выгрузки за один обход площадки.
      </p>
      <p v-else class="faint small">
        Первый снимок получит указанное время, каждый следующий — плюс интервал, в порядке выбора файлов.
      </p>
        </div>
      </div>
      <p v-if="error" class="error" role="alert">{{ error }}</p>
      <ul v-if="errors.length" class="error small"><li v-for="(e, i) in errors" :key="i">{{ e.file }}: {{ e.error }}</li></ul>
    </form>

    <CameraPanel :project-id="building.project_id" :building-id="building.id"
      :buildings="[building]" @changed="onCamerasChanged" />

    <section class="panel">
      <div class="panel-head">
        <div>
          <h2>Снимки объекта</h2>
          <p class="faint small">{{ countLabel(total, 'снимок', 'снимка', 'снимков') }}. Отметьте два кадра, чтобы сравнить «было — стало».</p>
        </div>
        <div class="filters">
          <label class="field">Камера
            <select v-model="filters.camera_id" @change="loadPhotos()">
              <option value="">все</option>
              <option v-for="c in uploadCameras" :key="c.id" :value="String(c.id)">{{ c.name }}</option>
            </select></label>
          <label class="field">Техника
            <select v-model="filters.cls" @change="loadPhotos()">
              <option value="">любая</option>
              <option v-for="e in equipment" :key="e.cls" :value="e.cls">{{ e.label }}</option>
            </select></label>
          <label class="field">С<input v-model="filters.taken_from" type="date" @change="loadPhotos()" /></label>
          <label class="field">По<input v-model="filters.taken_to" type="date" @change="loadPhotos()" /></label>
        </div>
      </div>
      <div v-if="!photos.length" class="empty"><p>Снимков пока нет. Загрузите фото или запустите эмулятор камеры.</p></div>
      <ul v-else class="gallery">
        <li v-for="p in photos" :key="p.id">
          <button type="button" class="shot" :class="{ picked: compare.includes(p.id) }" @click="openId = p.id">
            <span class="shot-img">
              <img :src="imageUrl(p.id, 480)" :alt="`Снимок от ${formatDateTime(p.taken_at)}`" loading="lazy" />
              <span class="shot-time">{{ formatDateTime(p.taken_at) }}</span>
            </span>
            <span class="pick" :class="{ on: compare.includes(p.id) }" role="checkbox"
              :aria-checked="compare.includes(p.id)" :title="'Сравнить'" @click.stop="toggleCompare(p.id)">
              {{ compare.indexOf(p.id) + 1 || '' }}
            </span>
            <span class="shot-meta">
              <span class="faint small">{{ p.camera_name || 'без камеры' }}</span>
              <span class="eq">
                <span v-for="e in p.equipment" :key="e.cls" class="tag">{{ e.label }}<template v-if="e.count > 1"> ×{{ e.count }}</template></span>
                <span v-if="!p.equipment.length" class="faint small">техника не найдена</span>
              </span>
            </span>
          </button>
        </li>
      </ul>
      <div v-if="photos.length < total" class="more">
        <button class="btn" type="button" @click="loadPhotos(true)">Показать ещё</button>
      </div>
    </section>

    <PhotoCompare v-if="compare.length === 2" :ids="compare" :photos="photos" @close="compare = []" />

    <PhotoInspector v-if="openId" :photo-id="openId" :classes="classes" @close="openId = null" @changed="onCamerasChanged" />
  </section>
</template>

<style scoped>
.upload { display: grid; grid-template-columns: minmax(0, 1.4fr) minmax(300px, 1fr); gap: 28px; }
.drop {
  display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 8px; min-height: 240px; padding: 28px;
  border: 1px dashed var(--hair-2); border-radius: var(--r-l); background: rgba(236, 235, 230, 0.015); cursor: pointer; text-align: center;
  transition: border-color 0.3s var(--ease), background 0.3s var(--ease);
}
.drop:hover, .drop.over { border-color: var(--accent); background: var(--accent-soft); }
.drop.filled { border-style: solid; border-color: rgba(205, 183, 143, 0.5); }
.drop b { font-weight: 500; }
.drop-icon { width: 56px; height: 56px; border-radius: 50%; border: 1px solid rgba(205, 183, 143, 0.45); color: var(--accent); display: grid; place-items: center; margin-bottom: 10px; }
.drop-icon svg { width: 22px; height: 22px; }
.upload-fields { display: flex; flex-direction: column; gap: 16px; }
.mode { display: flex; gap: 4px; padding: 4px; border: 1px solid var(--hair); border-radius: var(--r-s); }
.mode button { flex: 1; font: inherit; font-size: 13px; padding: 7px 10px; border: 0; border-radius: 6px;
  background: transparent; color: var(--ink-2); cursor: pointer; }
.mode button.on { background: rgba(236, 235, 230, 0.08); color: var(--ink); }
.upload-fields .btn { min-height: 48px; }
.upload-fields p { margin: 0; }
.warn-hint { color: var(--warning); margin: 0; }
.gallery { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(auto-fill, minmax(270px, 1fr)); gap: 22px; }
.shot { display: block; width: 100%; text-align: left; font: inherit; color: inherit; background: none; border: 0; padding: 0; cursor: zoom-in; }
.shot-img { position: relative; display: block; aspect-ratio: 4 / 3; border-radius: var(--r-m); overflow: hidden; background: var(--panel-2); }
.shot-img img { width: 100%; height: 100%; object-fit: cover; display: block; transition: transform 1s var(--ease); }
.shot:hover img { transform: scale(1.05); }
.filters { display: flex; gap: 10px; flex-wrap: wrap; }
.filters .field { font-size: 12px; }
.filters select, .filters input { padding: 6px 9px; font-size: 13px; }
.pick { position: absolute; top: 10px; right: 10px; width: 26px; height: 26px; border-radius: 50%; display: grid; place-items: center;
  background: rgba(10, 14, 16, 0.6); border: 1px solid rgba(236, 235, 230, 0.25); color: var(--ink); font-size: 12px;
  backdrop-filter: blur(8px); cursor: pointer; }
.pick.on { background: var(--accent); border-color: var(--accent); color: var(--accent-ink); font-weight: 600; }
.shot.picked .shot-img { outline: 1.5px solid var(--accent); outline-offset: 2px; }
.shot-time { position: absolute; left: 12px; bottom: 12px; padding: 4px 11px; border-radius: 999px; background: rgba(10, 14, 16, 0.55); border: 1px solid rgba(236, 235, 230, 0.12); backdrop-filter: blur(10px); -webkit-backdrop-filter: blur(10px); color: var(--ink); font-size: 12px; }
.shot-meta { display: grid; gap: 8px; padding: 12px 2px 0; }
.eq { display: flex; flex-wrap: wrap; gap: 6px; }
.more { display: flex; justify-content: center; margin-top: 24px; }
@media (max-width: 900px) { .upload { grid-template-columns: 1fr; } }
</style>
