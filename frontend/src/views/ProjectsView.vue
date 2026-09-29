<script setup>
import { onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, reportUrl } from '../api.js'
import { refreshNav, ui } from '../store.js'
import { formatDate, countLabel } from '../lib/format.js'
import { projectSummary } from '../lib/project-summary.js'
import Icon from '../components/Icon.vue'
import ProjectsMap from '../components/ProjectsMap.vue'

const route = useRoute()
const router = useRouter()
const projects = ref([])
const summaries = ref({})
const loading = ref(true)
const error = ref('')
const dialog = ref(null)
const busy = ref(false)
const form = ref({ name: '', address: '', start_date: '', end_date: '' })
const formError = ref('')
const statusLabels = { ok: 'Всё по плану', warning: 'Есть отклонения', critical: 'Критические отклонения', unknown: 'Недостаточно данных' }
let generation = 0

async function load() {
  const current = ++generation
  loading.value = true
  error.value = ''
  summaries.value = {}
  try {
    const result = await api.projects()
    if (current !== generation) return
    projects.value = result
    loading.value = false
    const queue = [...result]
    await Promise.all(Array.from({ length: Math.min(3, queue.length) }, async () => {
      while (queue.length && current === generation) {
        const project = queue.shift()
        try {
          const overview = await api.overview(project.id)
          if (current === generation) summaries.value[project.id] = projectSummary(overview.buildings)
        } catch {
          if (current === generation) summaries.value[project.id] = { error: true }
        }
      }
    }))
  } catch (e) {
    if (current === generation) error.value = e.message
  } finally {
    if (current === generation) loading.value = false
  }
}
function openForm() {
  formError.value = ''
  dialog.value?.showModal()
}
function closeForm() {
  if (busy.value) return
  dialog.value?.close()
  if (route.query.new) {
    const { new: discarded, ...query } = route.query
    router.replace({ path: '/', query })
  }
}
function backdrop(event) {
  if (event.target !== dialog.value) return
  const box = dialog.value.getBoundingClientRect()
  if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) closeForm()
}
async function create() {
  if (busy.value) return
  formError.value = ''
  if (!form.value.name.trim()) { formError.value = 'Введите название стройки.'; return }
  if (form.value.end_date <= form.value.start_date) { formError.value = 'Дата ввода должна быть позже начала работ.'; return }
  busy.value = true
  try {
    const project = await api.createProject({ ...form.value, name: form.value.name.trim(), address: form.value.address.trim() })
    refreshNav()
    dialog.value?.close()
    await router.push(`/projects/${project.id}`)
  } catch (e) { formError.value = e.message }
  finally { busy.value = false }
}
watch(() => route.query.new, value => { if (value) openForm(); else if (!busy.value) dialog.value?.close() })
onMounted(() => {
  Object.assign(ui, { crumbs: [], projectId: null, buildingId: null })
  if (route.query.new) openForm()
  load()
})
onBeforeUnmount(() => { generation++ })
</script>

<template>
  <main class="projects-page">
    <header class="projects-heading">
      <div><h1>Стройки</h1><p>{{ countLabel(projects.length, 'стройка', 'стройки', 'строек') }} под наблюдением камер</p></div>
      <button class="btn primary" type="button" @click="openForm"><Icon name="plus" />Новая стройка</button>
    </header>
    <div v-if="error" class="projects-notice" role="alert"><p>{{ error }}</p><button class="btn" @click="load">Повторить загрузку</button></div>
    <p v-else-if="loading" class="projects-notice" role="status">Загружаем стройки…</p>
    <div v-else-if="!projects.length" class="projects-notice"><h2>Первая стройка начинается здесь</h2><p>Добавьте название, адрес и сроки работ.</p><button class="btn primary" @click="openForm">Новая стройка</button></div>
    <ul v-else class="construction-list">
      <li v-for="p in projects" :key="p.id">
        <article class="construction-card">
          <RouterLink :to="`/projects/${p.id}`" class="construction-cover">
            <span class="construction-status" :class="summaries[p.id]?.status || 'unknown'">{{ summaries[p.id]?.error ? 'Показатели недоступны' : summaries[p.id] ? statusLabels[summaries[p.id].status] : 'Загрузка показателей…' }}</span>
            <h2>{{ p.name }}</h2><p>{{ p.address || 'Адрес не указан' }}</p>
          </RouterLink>
          <div class="construction-facts">
            <div class="construction-progress" title="Готовность и план — среднее по объектам, с одинаковым весом каждого объекта. При неполных данных готовность не рассчитывается.">
              <span class="fact-label">ГОТОВНОСТЬ</span>
              <div class="progress-values"><strong>{{ summaries[p.id]?.actual == null ? '—' : summaries[p.id].actual + '%' }}</strong><span>план {{ summaries[p.id]?.planned == null ? '—' : summaries[p.id].planned + '%' }}</span></div>
              <div class="construction-bar" aria-hidden="true"><i :style="{ width: Math.max(0, Math.min(100, summaries[p.id]?.actual || 0)) + '%' }"></i><b v-if="summaries[p.id]?.planned != null" :style="{ left: Math.max(0, Math.min(100, summaries[p.id].planned)) + '%' }"></b></div>
            </div>
            <div><span class="fact-label">ОБЪЕКТЫ</span><span class="fact-value">{{ p.buildings_count ?? '—' }}</span></div>
            <div><span class="fact-label">КАМЕРЫ</span><span class="fact-value">{{ p.cameras_count ?? '—' }}</span></div>
            <div title="Самая поздняя прогнозная дата среди объектов. Отображается, только когда прогноз есть у каждого объекта."><span class="fact-label">ПРОГНОЗ</span><span class="fact-value forecast">{{ summaries[p.id]?.forecast ? formatDate(summaries[p.id].forecast) : '—' }}</span></div>
            <a class="construction-report" :href="reportUrl(p.id)" target="_blank" rel="noopener" title="Откроется отчёт. Для сохранения PDF используйте печать браузера."><Icon name="report" /><span><b>Отчёт</b><strong>Открыть отчёт</strong><small>Печать → PDF</small></span></a>
          </div>
          <p v-if="summaries[p.id]?.error" class="summary-error">Не удалось загрузить показатели. <button type="button" @click="load">Повторить</button></p>
        </article>
      </li>
    </ul>
    <ProjectsMap v-if="!loading && !error && projects.length" :projects="projects" :summaries="summaries" />
    <dialog ref="dialog" class="new-construction" aria-labelledby="new-title" aria-describedby="new-description" @cancel.prevent="closeForm" @click="backdrop">
      <form @submit.prevent="create" :aria-busy="busy">
        <button class="modal-close" type="button" aria-label="Закрыть" :disabled="busy" @click="closeForm"><Icon name="close" /></button>
        <h2 id="new-title">Новая стройка</h2>
        <p id="new-description">Сроки стройки станут сроками её объектов по умолчанию.</p>
        <div class="construction-form">
          <label class="field form-wide">Название<input v-model="form.name" autofocus required placeholder="ЖК «Северный парк»" :disabled="busy" /></label>
          <label class="field form-wide">Адрес<input v-model="form.address" placeholder="Москва, Дмитровское шоссе, вл. 1" :disabled="busy" /></label>
          <label class="field">Начало работ<input v-model="form.start_date" type="date" required :disabled="busy" /></label>
          <label class="field">Ввод в эксплуатацию<input v-model="form.end_date" type="date" required :min="form.start_date" :disabled="busy" /></label>
          <div class="create-actions"><button class="btn primary" type="submit" :disabled="busy">{{ busy ? 'Создаём…' : 'Создать стройку' }}</button></div>
        </div>
        <p v-if="formError" class="error" role="alert">{{ formError }}</p>
      </form>
    </dialog>
  </main>
</template>
