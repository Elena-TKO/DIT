<script setup>
import { computed, onMounted, ref } from 'vue'
import { api } from '../api.js'
import { formatDateTime } from '../lib/format.js'
import Icon from './Icon.vue'

// Камера — метка точки съёмки (название + зона + объект). Снимки загружаются вручную и привязываются к камере,
// чтобы анализ сравнивал соседние кадры одной точки: так определяется «работает / стоит» и считается простой.
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
const editId = ref(null)
const edit = ref({ name: '', zone: '' })
const blank = () => ({ name: '', zone: '', building_id: props.buildingId || null })
const form = ref(blank())

const visible = computed(() => props.buildingId
  ? cameras.value.filter((c) => !c.building_id || c.building_id === props.buildingId)
  : cameras.value)
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
  } finally {
    busyId.value = null
  }
}

async function create() {
  error.value = ''
  if (!form.value.name.trim()) { error.value = 'Укажите название камеры.'; return }
  try {
    await api.createCamera(props.projectId, {
      name: form.value.name.trim(), zone: form.value.zone.trim(), building_id: form.value.building_id || null,
    })
    form.value = blank()
    showForm.value = false
    await load()
    emit('changed')
  } catch (e) {
    error.value = e.message
  }
}

function startEdit(camera) {
  editId.value = camera.id
  edit.value = { name: camera.name, zone: camera.zone || '' }
}

function saveEdit(camera) {
  if (!edit.value.name.trim()) { error.value = 'Название камеры не может быть пустым.'; return }
  act(camera, async () => {
    await api.updateCamera(camera.id, { name: edit.value.name.trim(), zone: edit.value.zone.trim() })
    editId.value = null
  })
}

function remove(camera) {
  if (window.confirm(`Удалить камеру «${camera.name}»? Снимки останутся, но без привязки к камере.`)) {
    act(camera, () => api.deleteCamera(camera.id))
  }
}

onMounted(load)
defineExpose({ load })
</script>

<template>
  <section class="panel">
    <div class="panel-head">
      <div>
        <h2>Камеры</h2>
        <p class="muted small">Камера — точка съёмки на площадке. Привяжите к ней снимки при загрузке: по соседним кадрам одной камеры определяется, работает техника или стоит.</p>
      </div>
      <button class="btn" type="button" @click="showForm = !showForm"><Icon name="plus" />Добавить камеру</button>
    </div>

    <form v-if="showForm" class="cam-form" @submit.prevent="create">
      <div class="cam-grid">
        <label class="field">Название<input v-model="form.name" required placeholder="Обзорная, мачта" /></label>
        <label class="field">Зона площадки<input v-model="form.zone" placeholder="Котлован" /></label>
        <label class="field">Объект
          <select v-model="form.building_id">
            <option :value="null">Любой объект</option>
            <option v-for="b in buildings" :key="b.id" :value="b.id">{{ b.name }}</option>
          </select></label>
      </div>
      <div class="cam-form-foot">
        <button class="btn ghost" type="button" @click="showForm = false">Отмена</button>
        <button class="btn primary" type="submit">Сохранить камеру</button>
      </div>
    </form>

    <p v-if="error" class="error" role="alert">{{ error }}</p>

    <div v-if="!visible.length" class="empty small">
      <p>Камер нет. Добавьте камеру и выбирайте её при загрузке снимков.</p>
    </div>
    <ul v-else class="cams">
      <li v-for="c in visible" :key="c.id" class="cam">
        <span class="cam-icon"><Icon name="camera" /></span>
        <div v-if="editId === c.id" class="cam-edit">
          <input v-model="edit.name" aria-label="Название камеры" />
          <input v-model="edit.zone" aria-label="Зона площадки" placeholder="Зона площадки" />
        </div>
        <div v-else class="cam-main">
          <b>{{ c.name }}</b>
          <span class="muted small">{{ c.zone || 'зона не указана' }}, {{ buildingName(c.building_id) }}</span>
        </div>
        <div class="cam-meta small">
          <span>{{ c.photos_count }} сним.</span>
          <span class="faint">{{ c.last_photo_at ? 'последний ' + formatDateTime(c.last_photo_at) : 'снимков ещё нет' }}</span>
        </div>
        <div class="cam-actions">
          <template v-if="editId === c.id">
            <button class="btn small primary" type="button" :disabled="busyId === c.id" @click="saveEdit(c)">Сохранить</button>
            <button class="btn small ghost" type="button" @click="editId = null">Отмена</button>
          </template>
          <button v-else class="btn small ghost" type="button" :disabled="busyId === c.id" @click="startEdit(c)">Изменить</button>
          <button class="btn small ghost" type="button" :disabled="busyId === c.id" aria-label="Удалить камеру" title="Удалить" @click="remove(c)"><Icon name="close" /></button>
        </div>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.cam-form { background: var(--panel-2); border: 1px solid var(--hair); border-radius: var(--r-m); padding: 22px; margin-bottom: 22px; }
.cam-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; }
.cam-form-foot { display: flex; justify-content: flex-end; gap: 10px; margin-top: 18px; }
.cams { list-style: none; margin: 0; padding: 0; }
.cam { display: grid; grid-template-columns: 46px minmax(0, 1.4fr) minmax(0, 1fr) auto; gap: 20px; align-items: center; padding: 16px 0; border-top: 1px solid var(--hair); }
.cam:first-child { border-top: 0; padding-top: 4px; }
.cam-icon { width: 46px; height: 46px; border-radius: 13px; border: 1px solid var(--hair-2); color: var(--ink-3); display: grid; place-items: center; }
.cam-icon svg { width: 20px; height: 20px; }
.cam-main, .cam-meta { display: grid; gap: 2px; min-width: 0; }
.cam-main b { font-weight: 500; }
.cam-edit { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.cam-edit input { padding: 6px 9px; font-size: 13px; }
.cam-actions { display: flex; gap: 6px; justify-content: flex-end; flex-wrap: wrap; }
@media (max-width: 1100px) {
  .cam { grid-template-columns: 46px 1fr; }
  .cam-meta, .cam-actions { grid-column: 2; justify-content: flex-start; }
  .cam-grid { grid-template-columns: 1fr; }
}
</style>
