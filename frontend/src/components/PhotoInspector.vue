<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api, imageUrl } from '../api.js'
import { formatDateTime } from '../lib/format.js'
import { ACTIVITY, classColor } from '../lib/labels.js'
import Icon from './Icon.vue'

const props = defineProps({
  photoId: { type: Number, required: true },
  classes: { type: Array, default: () => [] },
})
const emit = defineEmits(['close', 'changed'])

const photo = ref(null)
const dialog = ref(null)
let lastFocused = null
const error = ref('')
const busy = ref(false)
const showWeak = ref(false)

const shown = computed(() => (photo.value?.detections || [])
  .filter((d) => showWeak.value || d.confidence >= photo.value.min_confidence))

async function load() {
  error.value = ''
  try {
    photo.value = await api.photo(props.photoId)
  } catch (e) {
    error.value = e.message
  }
}

async function run(fn, closeAfter = false) {
  busy.value = true
  try {
    const result = await fn()
    emit('changed')
    if (closeAfter) emit('close')
    else if (result) photo.value = result
  } catch (e) {
    error.value = e.message
  } finally {
    busy.value = false
  }
}

function removeDetection(det) {
  const items = photo.value.detections.filter((d) => d.id !== det.id)
    .map((d) => ({ cls: d.cls, bbox: d.bbox, confidence: d.confidence }))
  run(() => api.replaceDetections(props.photoId, items))
}

function removePhoto() {
  if (window.confirm('Удалить снимок из анализа?')) run(() => api.deletePhoto(props.photoId), true)
}

function onKey(e) {
  if (e.key === 'Escape') {
    emit('close')
    return
  }
  if (e.key !== 'Tab' || !dialog.value) return
  // Фокус не должен уходить из открытого окна: иначе с клавиатуры пользователь «теряется» на фоне
  const items = [...dialog.value.querySelectorAll('a[href], button:not([disabled]), input, select, [tabindex]:not([tabindex="-1"])')]
    .filter((el) => el.offsetParent !== null)
  if (!items.length) return
  const first = items[0]
  const last = items[items.length - 1]
  if (e.shiftKey && document.activeElement === first) {
    e.preventDefault()
    last.focus()
  } else if (!e.shiftKey && document.activeElement === last) {
    e.preventDefault()
    first.focus()
  }
}

watch(() => props.photoId, load)
onMounted(async () => {
  lastFocused = document.activeElement
  document.body.style.overflow = 'hidden'
  window.addEventListener('keydown', onKey)
  await load()
  await nextTick()
  dialog.value?.focus()
})
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKey)
  document.body.style.overflow = ''
  lastFocused?.focus?.()          // возвращаем фокус на снимок, с которого открыли окно
})
</script>

<template>
  <div class="modal-back" @click.self="emit('close')">
    <div ref="dialog" class="lightbox" role="dialog" aria-modal="true" aria-label="Снимок" tabindex="-1">
      <div class="stage">
        <div class="stage-head">
          <div>
            <b>{{ photo ? formatDateTime(photo.taken_at) : 'Снимок' }}</b>
            <span v-if="photo" class="stage-sub">
              {{ photo.camera_name || 'без камеры' }}{{ photo.zone ? `, зона «${photo.zone}»` : '' }}
            </span>
          </div>
          <button class="btn small glass" type="button" aria-label="Закрыть" @click="emit('close')"><Icon name="close" /></button>
        </div>
        <div v-if="photo" class="frame">
          <img :src="imageUrl(photo.id, 1600)" :alt="`Снимок ${photo.id}`" />
          <div v-for="d in shown" :key="d.id" class="box" :class="{ weak: d.confidence < photo.min_confidence }"
            :style="{ left: d.bbox[0] * 100 + '%', top: d.bbox[1] * 100 + '%', width: (d.bbox[2] - d.bbox[0]) * 100 + '%',
                      height: (d.bbox[3] - d.bbox[1]) * 100 + '%', borderColor: classColor(d.cls, classes) }">
            <span class="tag" :style="{ background: classColor(d.cls, classes) }">
              {{ d.label }} {{ Math.round(d.confidence * 100) }}%<template v-if="d.activity === 'idle'">, стоит {{ d.idle_minutes }} мин</template>
            </span>
          </div>
        </div>
      </div>
      <aside v-if="photo" class="side">
        <p v-if="error" class="error">{{ error }}</p>
        <section>
          <h3>Этап по этому снимку</h3>
          <p class="small">{{ photo.stage.explanation }}</p>
          <p class="faint small">По графику на эту дату: {{ photo.planned_phases.map((p) => p.name).join(', ') || 'нет работ' }}</p>
        </section>
        <section>
          <div class="section-head">
            <h3>Техника</h3>
            <label class="toggle small"><input v-model="showWeak" type="checkbox" />неуверенные</label>
          </div>
          <p v-if="!shown.length" class="faint small">Техника не обнаружена.</p>
          <ul v-else class="dets">
            <li v-for="d in shown" :key="d.id">
              <span class="swatch" :style="{ background: classColor(d.cls, classes) }"></span>
              <span class="det-name">{{ d.label }}<span class="faint small">{{ ACTIVITY[d.activity] }}{{ d.manual ? ', вручную' : '' }}</span></span>
              <span class="small">{{ Math.round(d.confidence * 100) }}%</span>
              <button class="btn small ghost" type="button" :disabled="busy" title="Убрать ошибочную рамку" aria-label="Убрать рамку"
                @click="removeDetection(d)"><Icon name="close" /></button>
            </li>
          </ul>
        </section>
        <section class="side-foot">
          <p class="faint small">{{ photo.original_name }}; детектор {{ photo.detector }}, {{ photo.process_ms }} мс</p>
          <div class="row">
            <button class="btn small" type="button" :disabled="busy" @click="run(() => api.redetect(photo.id))"><Icon name="refresh" />Распознать заново</button>
            <button class="btn small ghost danger" type="button" :disabled="busy" @click="removePhoto">Удалить снимок</button>
          </div>
        </section>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.lightbox { display: grid; grid-template-columns: minmax(0, 1fr) 380px; width: min(1440px, 100%); max-height: calc(100vh - 48px); border-radius: var(--r-xl); overflow: hidden; background: #070A0B; border: 1px solid var(--hair); box-shadow: var(--shadow); }
.stage { display: flex; flex-direction: column; min-width: 0; padding: 20px 24px 24px; }
.stage-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; gap: 16px; }
.stage-head b { font-family: var(--serif); font-size: 24px; font-weight: 500; font-variant-numeric: lining-nums; }
.stage-sub { display: block; font-size: 13px; color: var(--ink-3); }
.frame { position: relative; align-self: center; line-height: 0; }
.frame img { max-width: 100%; max-height: calc(100vh - 150px); display: block; border-radius: var(--r-s); }
.box { position: absolute; border: 1.5px solid; border-radius: 3px; line-height: 1.2; box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.25); }
.box.weak { border-style: dashed; opacity: 0.7; }
.tag { position: absolute; left: -1.5px; bottom: calc(100% + 3px); height: auto; border: 0; color: #111; font-size: 11.5px; font-weight: 600; padding: 2px 7px; border-radius: 4px; white-space: nowrap; }
.side { background: var(--panel); border-left: 1px solid var(--hair); padding: 26px; overflow-y: auto; display: flex; flex-direction: column; gap: 26px; }
.side h3 { margin-bottom: 10px; }
.side p { margin: 0 0 6px; }
.toggle { display: inline-flex; align-items: center; gap: 8px; color: var(--ink-3); cursor: pointer; }
.dets { list-style: none; margin: 0; padding: 0; }
.dets li { display: grid; grid-template-columns: 9px 1fr auto auto; gap: 12px; align-items: center; padding: 9px 0; border-top: 1px solid var(--hair); font-size: 13.5px; }
.dets li:first-child { border-top: 0; }
.det-name { display: grid; }
.side-foot { margin-top: auto; padding-top: 18px; border-top: 1px solid var(--hair); }
@media (max-width: 1000px) { .lightbox { grid-template-columns: 1fr; overflow-y: auto; } .side { border-left: 0; border-top: 1px solid var(--hair); } }
</style>
