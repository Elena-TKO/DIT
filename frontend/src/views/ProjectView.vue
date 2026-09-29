<script setup>
import { onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { api, imageUrl, reportUrl } from '../api.js'
import { refreshNav, ui } from '../store.js'
import { formatDate, countLabel, money } from '../lib/format.js'
import { PCT, RISK } from '../lib/labels.js'
import CameraPanel from '../components/CameraPanel.vue'
import Icon from '../components/Icon.vue'
import StatusPill from '../components/StatusPill.vue'

const props = defineProps({ id: { type: Number, required: true } })
const router = useRouter()

const overview = ref(null)
const types = ref([])
const error = ref('')
const showForm = ref(false)
const form = ref({ name: '', object_type: 'housing', start_date: '', end_date: '' })
const formError = ref('')
const creating = ref(false)

async function load() {
  try {
    overview.value = await api.overview(props.id)
    Object.assign(ui, { crumbs: [{ to: '/', label: 'Стройки' }], projectId: props.id, buildingId: null })
    error.value = ''
  } catch (e) {
    error.value = e.message
  }
}

async function createBuilding() {
  formError.value = ''
  creating.value = true
  try {
    const b = await api.createBuilding(props.id, form.value)
    refreshNav()
    router.push(`/buildings/${b.id}/photos`)
  } catch (e) {
    formError.value = e.message
  } finally {
    creating.value = false
  }
}

async function removeProject() {
  if (!window.confirm('Удалить стройку со всеми объектами, камерами и снимками?')) return
  await api.deleteProject(props.id)
  refreshNav()
  router.push('/')
}

onMounted(async () => {
  types.value = await api.objectTypes().catch(() => [])
  await load()
})
watch(() => props.id, load)
</script>

<template>
  <main class="page">
    <p v-if="error" class="error">{{ error }}</p>
    <template v-if="overview">
      <nav class="crumbs"><RouterLink to="/">Стройки</RouterLink><span>/</span><span>{{ overview.project.name }}</span></nav>
      <header class="page-head">
        <div>
          <h1>{{ overview.project.name }}</h1>
          <p class="lead">
            {{ overview.project.address || 'Адрес не указан' }}, {{ formatDate(overview.project.start_date) }} — {{ formatDate(overview.project.end_date) }}
          </p>
        </div>
        <div class="row">
          <a class="btn" :href="reportUrl(id)" target="_blank" rel="noopener"><Icon name="report" />Отчёт по стройке</a>
          <button class="btn primary" type="button" @click="showForm = !showForm"><Icon name="plus" />Добавить объект</button>
        </div>
      </header>

      <form v-if="showForm" class="panel add-form" @submit.prevent="createBuilding">
        <div class="panel-head">
          <div>
            <h2>Новый объект</h2>
            <p class="muted small">План работ сформируется по справочнику для выбранного типа — на следующем шаге его можно поправить.</p>
          </div>
          <button class="btn ghost small" type="button" aria-label="Закрыть" @click="showForm = false"><Icon name="close" /></button>
        </div>
        <div class="form-grid">
          <label class="field">Название<input v-model="form.name" required placeholder="Корпус 1" /></label>
          <label class="field">Тип объекта
            <select v-model="form.object_type">
              <option v-for="t in types" :key="t.key" :value="t.key">{{ t.title }}</option>
            </select></label>
          <label class="field">Начало<input v-model="form.start_date" type="date" /></label>
          <label class="field">Окончание<input v-model="form.end_date" type="date" /></label>
        </div>
        <div class="form-foot">
          <span class="muted small">
            Если сроки не указать, объект возьмёт сроки стройки:
            {{ formatDate(overview.project.start_date) }} — {{ formatDate(overview.project.end_date) }}.
          </span>
          <p v-if="formError" class="error">{{ formError }}</p>
          <button class="btn primary" type="submit" :disabled="creating">Создать объект и план</button>
        </div>
      </form>

      <section class="objects">
        <div class="section-head">
          <h2>Объекты</h2>
          <span class="faint small">{{ countLabel(overview.buildings.length, 'объект', 'объекта', 'объектов') }}</span>
        </div>
        <div v-if="!overview.buildings.length" class="empty">
          <p>Добавьте объект — дом, школу или участок дороги.</p>
          <button class="btn primary" type="button" @click="showForm = true"><Icon name="plus" />Добавить объект</button>
        </div>
        <RouterLink v-for="b in overview.buildings" :key="b.id" :to="`/buildings/${b.id}/photos`" class="object">
          <div class="cover" :class="{ empty: !b.cover_photo_id }">
            <img v-if="b.cover_photo_id" :src="imageUrl(b.cover_photo_id, 480)" alt="" loading="lazy" />
          </div>
          <div class="object-main">
            <div class="object-title">
              <span class="object-name">{{ b.name }}</span>
              <StatusPill :status="b.photos ? b.status : ''" />
            </div>
            <p class="muted small">{{ b.object_type_title }}; {{ countLabel(b.photos, 'снимок', 'снимка', 'снимков') }}</p>
            <p class="stage small"><span class="faint">Фактический этап</span>
              <span :title="b.stage_note">{{ b.stage || (b.stage_closest ? `≈ ${b.stage_closest}` : 'не подтверждён') }}</span></p>
            <p v-if="b.idle_cost" class="stage small"><span class="faint">Простой техники</span>
              <span class="idle">{{ money(b.idle_cost, b.currency) }}</span></p>
          </div>
          <div class="object-progress">
            <div class="progress-label"><span class="figure-num">{{ PCT(b.completion_percent) }}</span><span class="faint small">по графику {{ b.planned_percent }}%</span></div>
            <div class="progress" :title="`Готовность ${PCT(b.completion_percent)}, по графику ${b.planned_percent}%`">
              <i :style="{ width: (b.completion_percent || 0) + '%' }"></i><b :style="{ left: b.planned_percent + '%' }"></b>
            </div>
          </div>
          <div class="object-forecast small">
            <span class="faint">Прогноз окончания</span>
            <b>{{ formatDate(b.forecast_end) }}</b>
            <span :class="`risk-${b.delay_risk}`">{{ RISK[b.delay_risk] }}</span>
          </div>
        </RouterLink>
      </section>

      <CameraPanel :project-id="id" :buildings="overview.buildings" @changed="load" />

      <div class="danger-zone">
        <button class="btn ghost small danger" type="button" @click="removeProject">Удалить стройку</button>
      </div>
    </template>
  </main>
</template>

<style scoped>
.add-form { margin-bottom: 36px; box-shadow: var(--shadow); }
.form-grid { display: grid; grid-template-columns: 2fr 2fr 1fr 1fr; gap: 18px; }
.form-foot { display: flex; align-items: center; justify-content: flex-end; gap: 16px; margin-top: 20px; }
.form-foot .muted { margin-right: auto; }
.objects { margin-bottom: 36px; }
.objects .section-head h2 { font-size: 30px; }
.object {
  display: grid; grid-template-columns: 220px minmax(0, 1.4fr) minmax(200px, 1fr) 190px; gap: 32px; align-items: center;
  padding: 14px 28px 14px 14px; background: var(--panel); border: 1px solid var(--hair); border-radius: var(--r-l);
  text-decoration: none; transition: border-color 0.4s var(--ease), background 0.4s var(--ease);
}
.object + .object { margin-top: 12px; }
.object:hover { border-color: var(--hair-2); background: var(--panel-2); }
.object:hover .cover img { transform: scale(1.05); }
.object .cover { aspect-ratio: 16 / 10; border-radius: var(--r-m); }
.object-title { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; margin-bottom: 4px; }
.object-name { font-family: var(--serif); font-size: 30px; line-height: 1.1; font-weight: 500; }
.object-main p { margin: 0; }
.stage { margin-top: 10px !important; display: flex; gap: 8px; flex-wrap: wrap; color: var(--ink-2); }
.progress-label { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 12px; }
.progress-label .figure-num { font-size: 38px; }
.progress-label small { font-size: 18px; }
.object-forecast { display: grid; gap: 3px; }
.object-forecast b { font-family: var(--serif); font-size: 22px; font-weight: 500; line-height: 1.2; font-variant-numeric: lining-nums; }
.idle { color: var(--accent); }
.risk-unknown { color: var(--ink-3); }
.risk-high { color: var(--critical); } .risk-medium { color: var(--warning); } .risk-low { color: var(--ok); }
.danger-zone { margin-top: 28px; display: flex; justify-content: flex-end; }
@media (max-width: 1100px) {
  .form-grid { grid-template-columns: 1fr 1fr; }
  .object { grid-template-columns: 140px 1fr; gap: 18px; }
  .object-progress, .object-forecast { grid-column: 1 / -1; }
}
</style>
