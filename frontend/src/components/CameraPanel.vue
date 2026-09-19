<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api } from '../api.js'
import { SOURCE_TYPES } from '../lib/labels.js'
import { formatDateTime, toLocalInput } from '../lib/format.js'
import Icon from './Icon.vue'

const props = defineProps({
  projectId: { type: Number, required: true },
  buildings: { type: Array, default: () => [] },
  buildingId: { type: Number, default: null },
})
const emit = defineEmits(['changed'])

const cameras = ref([])
const error = ref('')
const busyId = ref(null)
const showForm = ref(false)
const blank = () => ({
  name: '', source_type: 'emulator', zone: '', url: '', building_id: props.buildingId || props.buildings[0]?.id || null,
  interval_min: 30, tick_seconds: 10, emulator_start: toLocalInput(), active: false,
})
const form = ref(blank())
let timer = null

const visible = computed(() => props.buildingId
  ? cameras.value.filter((c) => !c.building_id || c.building_id === props.buildingId)
  : cameras.value)
const typeLabel = (key) => SOURCE_TYPES.find((t) => t.key === key)?.label || key
const buildingName = (id) => props.buildings.find((b) => b.id === id)?.name || 'Любой объект'

async function load() {
  try {
    cameras.value = await api.cameras(props.projectId)
    error.value = ''
  } catch (e) {
    error.value = e.message
  }
}

async function act(camera, fn) {
  busyId.value = camera.id
  error.value = ''
  try {
    await fn()
    await load()
    emit('changed')
  } catch (e) {
    error.value = `${camera.name}: ${e.message}`
    await load()
  } finally {
    busyId.value = null
  }
}

async function create() {
  error.value = ''
  try {
    const data = { ...form.value, building_id: form.value.building_id || null }
    await api.createCamera(props.projectId, data)
    form.value = blank()
    showForm.value = false
    await load()
    emit('changed')
  } catch (e) {
    error.value = e.message
  }
}

function onFrames(camera, event) {
  const files = [...event.target.files]
  event.target.value = ''
  if (files.length) act(camera, () => api.uploadFrames(camera.id, files))
}

function reset(camera) {
  const start = window.prompt('Время первого кадра (ГГГГ-ММ-ДДTЧЧ:ММ)', toLocalInput(camera.emulator_clock))
  if (start) act(camera, () => api.resetEmulator(camera.id, { start_at: start }))
}

function remove(camera) {
  if (window.confirm(`Удалить камеру «${camera.name}»? Снимки останутся.`)) act(camera, () => api.deleteCamera(camera.id))
}

watch(() => cameras.value.some((c) => c.active), (anyActive) => {
  clearInterval(timer)
  if (anyActive) {
    timer = setInterval(async () => {
      await load()
      emit('changed')
    }, 5000)
  }
})

onMounted(load)
onBeforeUnmount(() => clearInterval(timer))
defineExpose({ load })
</script>

<template>
  <section class="panel">
    <div class="panel-head">
      <div>
        <h2>Камеры</h2>
        <p class="muted small">Кадр раз в 30 минут. Эмулятор выдаёт кадры загруженной ленты с условным временем съёмки.</p>
      </div>
      <button class="btn" type="button" @click="showForm = !showForm"><Icon name="plus" />Добавить камеру</button>
    </div>

    <form v-if="showForm" class="cam-form" @submit.prevent="create">
      <div class="cam-grid">
        <label class="field">Название<input v-model="form.name" required placeholder="Обзорная, мачта" /></label>
        <label class="field">Источник
          <select v-model="form.source_type">
            <option v-for="t in SOURCE_TYPES" :key="t.key" :value="t.key">{{ t.label }}</option>
          </select></label>
        <label class="field">Зона площадки<input v-model="form.zone" placeholder="Котлован" /></label>
        <label class="field">Объект
          <select v-model="form.building_id">
            <option v-if="form.source_type === 'upload'" :value="null">Любой объект</option>
            <option v-for="b in buildings" :key="b.id" :value="b.id">{{ b.name }}</option>
          </select></label>
        <label v-if="form.source_type === 'http' || form.source_type === 'rtsp'" class="field wide">
          {{ form.source_type === 'http' ? 'Адрес снимка' : 'Адрес потока' }}
          <input v-model="form.url" required
            :placeholder="form.source_type === 'http' ? 'http://10.0.0.15/snapshot.jpg' : 'rtsp://user:pass@10.0.0.15:554/stream1'" />
        </label>
        <label v-if="form.source_type !== 'upload'" class="field">Интервал съёмки, мин
          <input v-model.number="form.interval_min" type="number" min="1" max="1440" /></label>
        <label v-if="form.source_type === 'emulator'" class="field">Новый кадр каждые, сек
          <input v-model.number="form.tick_seconds" type="number" min="1" max="3600" /></label>
        <label v-if="form.source_type === 'emulator'" class="field">Время первого кадра
          <input v-model="form.emulator_start" type="datetime-local" /></label>
      </div>
      <div class="cam-form-foot">
        <button class="btn ghost" type="button" @click="showForm = false">Отмена</button>
        <button class="btn primary" type="submit">Сохранить камеру</button>
      </div>
    </form>

    <p v-if="error" class="error" role="alert">{{ error }}</p>

    <div v-if="!visible.length" class="empty small">
      <p>Камер нет. Для демонстрации добавьте эмулятор, загрузите в него кадры и запустите.</p>
    </div>
    <ul v-else class="cams">
      <li v-for="c in visible" :key="c.id" class="cam">
        <span class="cam-icon" :class="{ live: c.active }"><Icon name="camera" /></span>
        <div class="cam-main">
          <b>{{ c.name }}</b>
          <span class="muted small">{{ c.zone || 'зона не указана' }}, {{ buildingName(c.building_id) }}</span>
          <span v-if="c.url" class="faint small url">{{ c.url }}</span>
        </div>
        <div class="cam-meta small">
          <span>{{ typeLabel(c.source_type) }}</span>
          <span class="faint">
            {{ c.photos_count }} сним.<template v-if="c.source_type === 'emulator'">, лента {{ c.emulator_cursor }} из {{ c.emulator_frames }}</template>
            <template v-if="c.last_photo_at">, последний {{ formatDateTime(c.last_photo_at) }}</template>
          </span>
          <span v-if="c.last_error" class="error small">{{ c.last_error }}</span>
        </div>
        <div class="cam-state">
          <span v-if="c.source_type === 'upload'" class="status">По загрузке</span>
          <span v-else-if="c.active" class="status ok live">Снимает, каждые {{ c.interval_min }} мин</span>
          <span v-else class="status">Остановлена</span>
        </div>
        <div class="cam-actions">
          <template v-if="c.source_type === 'emulator'">
            <label class="btn small"><Icon name="upload" />Кадры
              <input type="file" accept="image/*" multiple hidden @change="onFrames(c, $event)" />
            </label>
            <button class="btn small ghost" type="button" :disabled="busyId === c.id" title="Сбросить ленту" aria-label="Сбросить ленту" @click="reset(c)"><Icon name="refresh" /></button>
          </template>
          <template v-if="c.source_type !== 'upload'">
            <button class="btn small ghost" type="button" :disabled="busyId === c.id" @click="act(c, () => api.pollCamera(c.id))">Кадр сейчас</button>
            <button class="btn small" :class="c.active ? '' : 'primary'" type="button" :disabled="busyId === c.id"
              @click="act(c, () => api.updateCamera(c.id, { active: !c.active }))">
              <Icon :name="c.active ? 'pause' : 'play'" />{{ c.active ? 'Стоп' : 'Запустить' }}
            </button>
          </template>
          <button class="btn small ghost" type="button" :disabled="busyId === c.id" aria-label="Удалить камеру" title="Удалить" @click="remove(c)"><Icon name="close" /></button>
        </div>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.cam-form { background: var(--panel-2); border: 1px solid var(--hair); border-radius: var(--r-m); padding: 22px; margin-bottom: 22px; }
.cam-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 16px; }
.cam-grid .wide { grid-column: span 2; }
.cam-form-foot { display: flex; justify-content: flex-end; gap: 10px; margin-top: 18px; }
.cams { list-style: none; margin: 0; padding: 0; }
.cam { display: grid; grid-template-columns: 46px minmax(0, 1.2fr) minmax(0, 1.3fr) auto auto; gap: 20px; align-items: center; padding: 16px 0; border-top: 1px solid var(--hair); }
.cam:first-child { border-top: 0; padding-top: 4px; }
.cam-icon { width: 46px; height: 46px; border-radius: 13px; border: 1px solid var(--hair-2); color: var(--ink-3); display: grid; place-items: center; }
.cam-icon.live { border-color: rgba(205, 183, 143, 0.5); color: var(--accent); background: var(--accent-soft); }
.cam-icon svg { width: 20px; height: 20px; }
.cam-main, .cam-meta { display: grid; gap: 2px; min-width: 0; }
.cam-main b { font-weight: 500; }
.url { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cam-actions { display: flex; gap: 6px; justify-content: flex-end; flex-wrap: wrap; }
@media (max-width: 1100px) {
  .cam { grid-template-columns: 46px 1fr; }
  .cam-meta, .cam-state, .cam-actions { grid-column: 2; justify-content: flex-start; }
  .cam-grid { grid-template-columns: 1fr 1fr; }
}
</style>
