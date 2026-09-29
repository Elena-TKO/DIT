<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { api } from '../api.js'
import { refreshNav, ui } from '../store.js'
import PhotoReview from '../components/PhotoReview.vue'
import WorkPlan from '../components/WorkPlan.vue'
import PhotosPanel from '../components/PhotosPanel.vue'
import ReportPanel from '../components/ReportPanel.vue'

// Экраны «Мониторинг техники» и «Фото и отклонения» объединены в «Фото и техника»:
// вердикт по последнему снимку, «Снимки объекта» и «Камеры» на одной странице.
const props = defineProps({ id: { type: Number, required: true }, tab: { type: String, default: 'photos' } })
const building = ref(null)
const error = ref('')
const methodology = ref(null)
const version = ref(0)
const current = computed(() => (['plan', 'timeline'].includes(props.tab) ? 'plan' : props.tab === 'report' ? 'report' : 'photos'))
const classes = computed(() => (methodology.value?.equipment || []).map((e) => e.cls))
const steps = [{ key: 'photos', title: 'Фото и техника' }, { key: 'plan', title: 'План работ' }, { key: 'report', title: 'Отчёт' }]
let requestId = 0

async function load() {
  const request = ++requestId
  error.value = ''
  building.value = null
  try {
    const data = await api.building(props.id)
    if (request !== requestId) return
    building.value = data
    Object.assign(ui, { projectId: data.project.id, buildingId: props.id })
    scrollToCameras()
  } catch (e) {
    if (request === requestId) error.value = e.message
  }
}

function scrollToCameras() {
  // старая ссылка «Мониторинг техники» ведёт к блоку «Камеры» объединённого экрана
  if (props.tab !== 'cameras') return
  nextTick(() => setTimeout(() => document.getElementById('cameras')?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 300))
}

function changed() {
  version.value += 1
  refreshNav()
}

onMounted(() => {
  load()
  api.methodology().then((data) => { methodology.value = data }).catch(() => {})
})
watch(() => props.id, load)
watch(() => props.tab, scrollToCameras)
</script>

<template>
  <main class="building-workspace">
    <p v-if="error" class="error" role="alert">{{ error }} <button class="btn" @click="load">Повторить</button></p>
    <template v-else-if="building">
      <nav class="workspace-breadcrumbs" aria-label="Путь к объекту"><RouterLink to="/">Стройки</RouterLink><span>/</span><RouterLink :to="`/projects/${building.project.id}`">{{ building.project.name }}</RouterLink><span>/</span><b>{{ building.name }}</b></nav>
      <nav class="workspace-tabs" aria-label="Разделы объекта">
        <RouterLink v-for="s in steps" :key="s.key" :to="`/buildings/${id}/${s.key}`" :class="{ selected: current === s.key }" :aria-current="current === s.key ? 'page' : undefined">{{ s.title }}</RouterLink>
      </nav>
      <template v-if="current === 'photos'">
        <PhotoReview :key="`photo-${id}-${version}`" :building="building" @changed="changed" />
        <section class="legacy-light merged-monitoring">
          <PhotosPanel :key="`photos-${id}`" :building="building" :classes="classes" :equipment="methodology?.equipment || []"
            :phases="methodology?.phases || []" @changed="changed" />
        </section>
      </template>
      <WorkPlan v-else-if="current === 'plan'" :key="`plan-${id}`" :building="building" @changed="changed" />
      <section v-else class="legacy-light"><header class="review-heading"><h1>Отчёт</h1></header><ReportPanel :key="`report-${id}`" :building="building" /></section>
    </template>
    <p v-else role="status">Загружаем объект…</p>
  </main>
</template>

<style>
.merged-monitoring { margin-top: 32px; }
</style>
