<script setup>
import { onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, imageUrl } from '../api.js'
import { refreshNav, ui } from '../store.js'
import { formatDate, countLabel } from '../lib/format.js'
import Icon from '../components/Icon.vue'

const route = useRoute()
const router = useRouter()
const projects = ref([])
const loading = ref(true)
const error = ref('')
const showForm = ref(false)
const form = ref({ name: '', address: '', start_date: '', end_date: '' })
const formError = ref('')

async function load() {
  loading.value = true
  try {
    projects.value = await api.projects()
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

async function create() {
  formError.value = ''
  try {
    const p = await api.createProject(form.value)
    refreshNav()
    router.push(`/projects/${p.id}`)
  } catch (e) {
    formError.value = e.message
  }
}

watch(() => route.query.new, (v) => { if (v) showForm.value = true }, { immediate: true })
onMounted(() => {
  Object.assign(ui, { crumbs: [], projectId: null, buildingId: null })
  load()
})
</script>

<template>
  <main class="page">
    <header class="page-head">
      <div>
        <h1>Стройки</h1>
        <p class="lead">{{ projects.length ? countLabel(projects.length, 'стройка', 'стройки', 'строек') + ' под наблюдением камер' : 'Начните с создания стройки и сроков' }}</p>
      </div>
      <button class="btn primary" type="button" @click="showForm = !showForm"><Icon name="plus" />Новая стройка</button>
    </header>

    <form v-if="showForm" class="panel new-form" @submit.prevent="create">
      <div class="panel-head">
        <div>
          <h2>Новая стройка</h2>
          <p class="muted small">Сроки стройки станут сроками её объектов по умолчанию.</p>
        </div>
        <button class="btn ghost small" type="button" aria-label="Закрыть" @click="showForm = false"><Icon name="close" /></button>
      </div>
      <div class="form-grid">
        <label class="field span-2">Название<input v-model="form.name" required placeholder="ЖК «Северный парк»" /></label>
        <label class="field span-2">Адрес<input v-model="form.address" placeholder="Москва, Дмитровское шоссе, вл. 1" /></label>
        <label class="field">Начало работ<input v-model="form.start_date" type="date" required /></label>
        <label class="field">Ввод в эксплуатацию<input v-model="form.end_date" type="date" required /></label>
        <div class="form-actions span-2">
          <p v-if="formError" class="error">{{ formError }}</p>
          <button class="btn primary" type="submit">Создать стройку</button>
        </div>
      </div>
    </form>

    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="loading" class="muted">Загрузка…</p>
    <div v-else-if="!projects.length && !showForm" class="empty">
      <p>Строек пока нет. Создайте стройку, добавьте объект — план работ сформируется по справочнику.</p>
      <button class="btn primary" type="button" @click="showForm = true"><Icon name="plus" />Новая стройка</button>
    </div>
    <ul v-else class="projects">
      <li v-for="p in projects" :key="p.id">
        <RouterLink :to="`/projects/${p.id}`" class="project">
          <div class="cover" :class="{ empty: !p.cover_photo_id }">
            <img v-if="p.cover_photo_id" :src="imageUrl(p.cover_photo_id, 1000)" alt="" loading="lazy" />
            <div class="project-title">
              <h2>{{ p.name }}</h2>
              <p>{{ p.address || 'Адрес не указан' }}</p>
            </div>
            <span v-if="!p.cover_photo_id" class="cover-note small"><Icon name="camera" />Снимков пока нет</span>
          </div>
          <dl class="facts">
            <div><dt>Срок</dt><dd>{{ formatDate(p.start_date) }} — {{ formatDate(p.end_date) }}</dd></div>
            <div><dt>Объекты</dt><dd>{{ p.buildings_count }}</dd></div>
            <div><dt>Камеры</dt><dd>{{ p.cameras_count }}</dd></div>
          </dl>
        </RouterLink>
      </li>
    </ul>
  </main>
</template>

<style scoped>
.new-form { margin-bottom: 36px; box-shadow: var(--shadow); }
.form-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 18px; }
.span-2 { grid-column: span 2; }
.form-actions { display: flex; align-items: end; justify-content: flex-end; gap: 16px; }
.projects { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(auto-fill, minmax(460px, 1fr)); gap: 28px; }
.project { display: block; text-decoration: none; border-radius: var(--r-xl); overflow: hidden; background: var(--panel); border: 1px solid var(--hair); transition: border-color 0.4s var(--ease); }
.project:hover { border-color: var(--hair-2); }
.project:hover .cover img { transform: scale(1.04); }
.project .cover { aspect-ratio: 16 / 10; }
.project .cover::after { content: ""; position: absolute; inset: 0; background: linear-gradient(180deg, rgba(10, 14, 16, 0) 40%, rgba(10, 14, 16, 0.88) 100%); pointer-events: none; }
.project-title { position: absolute; left: 28px; right: 28px; bottom: 24px; z-index: 1; }
.project-title h2 { font-size: 36px; line-height: 1.05; margin-bottom: 6px; }
.project-title p { margin: 0; color: rgba(236, 235, 230, 0.72); font-size: 13.5px; }
.cover-note { position: absolute; top: 24px; left: 28px; display: flex; align-items: center; gap: 8px; color: var(--ink-3); }
.cover-note svg { width: 16px; height: 16px; }
.facts { display: grid; grid-template-columns: 2fr 1fr 1fr; margin: 0; padding: 18px 28px 22px; }
.facts > div + div { padding-left: 20px; border-left: 1px solid var(--hair); }
.facts dt { font-size: 12px; color: var(--ink-3); }
.facts dd { margin: 3px 0 0; font-size: 14px; }
@media (max-width: 700px) {
  .form-grid { grid-template-columns: 1fr; }
  .span-2 { grid-column: auto; }
  .projects { grid-template-columns: 1fr; }
  .project-title h2 { font-size: 28px; }
}
</style>
