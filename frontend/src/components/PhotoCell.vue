<script setup>
import { computed, nextTick, onBeforeUnmount, ref } from 'vue'
import { api } from '../api.js'
import { toLocalInput } from '../lib/format.js'
import Icon from './Icon.vue'

// Ячейка «Фото» этапа: «Загрузить» (фото ещё нет) или «Посмотреть фото» (ссылка на страницу этапа).
// При наведении — мини-окно быстрой дозагрузки одного или нескольких снимков на этот этап.
const props = defineProps({
  buildingId: { type: Number, required: true },
  stage: { type: Object, required: true },
})
const emit = defineEmits(['uploaded'])

const root = ref(null)
const fileInput = ref(null)
const open = ref(false)
const pos = ref({ top: 0, left: 0 })
const files = ref([])
const busy = ref(false)
const error = ref('')
const done = ref('')
const takenAt = ref('')
let closeTimer = null

const hasPhotos = computed(() => (props.stage.photos || 0) > 0)
const stageLink = computed(() => `/buildings/${props.buildingId}/stages/${props.stage.phase}`)

function defaultTime() {
  // следующий снимок — через 30 минут после последнего снимка этапа или в начале этапа по плану
  if (props.stage.photo_end) return toLocalInput(`${props.stage.photo_end}T12:00`)
  if (props.stage.start) return toLocalInput(`${props.stage.start}T09:00`)
  return toLocalInput()
}

function show() {
  clearTimeout(closeTimer)
  if (open.value) return
  const rect = root.value?.getBoundingClientRect()
  if (rect) {
    const width = 300
    pos.value = {
      top: Math.min(rect.bottom + 6, window.innerHeight - 250),
      left: Math.max(12, Math.min(rect.right - width, window.innerWidth - width - 12)),
    }
  }
  if (!takenAt.value) takenAt.value = defaultTime()
  error.value = ''
  done.value = ''
  open.value = true
}

function hideSoon() {
  if (busy.value) return
  clearTimeout(closeTimer)
  closeTimer = setTimeout(() => { open.value = false }, 250)
}

function pick(event) {
  const list = [...(event.target.files || [])]
  files.value = list.filter((f) => ['image/jpeg', 'image/png', 'image/webp', 'image/bmp'].includes(f.type))
  error.value = list.length !== files.value.length ? 'Часть файлов пропущена: подходят JPEG, PNG, WEBP, BMP.' : ''
  show()
}

function chooseFiles() {
  show()
  nextTick(() => fileInput.value?.click())
}

async function upload() {
  if (!files.value.length || busy.value) return
  busy.value = true
  error.value = ''
  try {
    const res = await api.uploadPhotos(props.buildingId, files.value, {
      phase: props.stage.phase, start_at: takenAt.value, interval_min: 30,
    })
    if (res.errors?.length) error.value = res.errors.map((e) => `${e.file}: ${e.error}`).join('; ')
    done.value = res.uploaded ? `Загружено ${res.uploaded} — анализ готов` : ''
    files.value = []
    if (fileInput.value) fileInput.value.value = ''
    if (res.uploaded) emit('uploaded', res)
  } catch (e) {
    error.value = e.message
  } finally {
    busy.value = false
  }
}

function onScroll() {
  if (open.value && !busy.value) open.value = false
}
window.addEventListener('scroll', onScroll, true)
onBeforeUnmount(() => {
  clearTimeout(closeTimer)
  window.removeEventListener('scroll', onScroll, true)
})
</script>

<template>
  <div ref="root" class="pc" @mouseenter="show" @mouseleave="hideSoon" @focusin="show">
    <RouterLink v-if="hasPhotos" :to="stageLink" class="pc-btn view"><Icon name="image" />Посмотреть фото<span class="pc-count">{{ stage.photos }}</span></RouterLink>
    <button v-else type="button" class="pc-btn" @click="chooseFiles"><Icon name="upload" />Загрузить</button>
    <input ref="fileInput" type="file" hidden multiple accept="image/jpeg,image/png,image/webp,image/bmp" @change="pick" />
    <Teleport to=".shell">
      <div v-if="open" class="pc-pop" :style="{ top: pos.top + 'px', left: pos.left + 'px' }" role="dialog"
        :aria-label="`Загрузка снимков на этап «${stage.name}»`" @mouseenter="show" @mouseleave="hideSoon">
        <b>{{ hasPhotos ? 'Дозагрузить снимки' : 'Загрузить снимки' }}</b>
        <span class="pc-sub">на этап «{{ stage.name }}»</span>
        <button type="button" class="pc-drop" :disabled="busy" @click="fileInput.click()">
          <Icon name="upload" />{{ files.length ? `Выбрано: ${files.length}` : 'Выбрать один или несколько файлов' }}
        </button>
        <label class="pc-field">Время первого снимка<input v-model="takenAt" type="datetime-local" :disabled="busy" /></label>
        <button type="button" class="pc-go" :disabled="busy || !files.length" @click="upload">
          {{ busy ? 'Распознаём технику…' : 'Загрузить и проанализировать' }}
        </button>
        <p v-if="done" class="pc-ok">{{ done }} · <RouterLink :to="stageLink">открыть этап</RouterLink></p>
        <p v-if="error" class="pc-err" role="alert">{{ error }}</p>
      </div>
    </Teleport>
  </div>
</template>

<style>
.pc { display: inline-block; }
.pc-btn { display: inline-flex; align-items: center; gap: 6px; white-space: nowrap; font: inherit; font-size: 12px; font-weight: 600; padding: 6px 10px; border-radius: 8px;
  border: 1px solid var(--hair-2); background: transparent; color: var(--accent); cursor: pointer; text-decoration: none; }
.pc-btn svg { width: 14px; height: 14px; }
.pc-btn.view { background: var(--accent); color: var(--accent-ink); border-color: var(--accent); }
.pc-count { font-size: 11px; padding: 0 6px; border-radius: 999px; background: rgba(255, 255, 255, 0.25); }
.pc-pop { position: fixed; z-index: 2000; width: 300px; display: grid; gap: 8px; padding: 14px; border-radius: 14px; background: var(--panel, #fff);
  color: var(--ink); border: 1px solid var(--hair-2); box-shadow: 0 18px 48px rgba(20, 30, 50, 0.22); font-size: 13px; }
.pc-pop b { font-size: 14px; }
.pc-sub { color: var(--ink-3); font-size: 12px; margin-top: -6px; }
.pc-drop { display: flex; align-items: center; gap: 8px; justify-content: center; padding: 14px 10px; border: 1.5px dashed var(--hair-2); border-radius: 10px;
  background: transparent; color: var(--ink); font: inherit; font-size: 12px; cursor: pointer; }
.pc-drop:hover { border-color: var(--accent); color: var(--accent); }
.pc-drop svg { width: 16px; height: 16px; }
.pc-field { display: grid; gap: 4px; font-size: 11px; color: var(--ink-3); }
.pc-field input { font: inherit; font-size: 12px; padding: 6px 8px; }
.pc-go { border: 0; border-radius: 9px; padding: 9px; background: var(--accent); color: var(--accent-ink); font: inherit; font-size: 12px; font-weight: 700; cursor: pointer; }
.pc-go:disabled { opacity: 0.5; cursor: default; }
.pc-ok { margin: 0; color: var(--ok); font-size: 12px; }
.pc-err { margin: 0; color: var(--critical); font-size: 12px; }
</style>
