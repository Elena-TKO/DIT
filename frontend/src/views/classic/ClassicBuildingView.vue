<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { api, imageUrl } from '../../api.js'
import { refreshNav, ui } from '../../store.js'
import { formatDate, formatDateTime } from '../../lib/format.js'
import { RISK } from '../../lib/labels.js'
import AnalysisPanel from '../../components/AnalysisPanel.vue'
import StagesOverview from '../../components/StagesOverview.vue'
import PhotosPanel from '../../components/PhotosPanel.vue'
import Gauge from '../../components/Gauge.vue'
import PlanEditor from '../../components/PlanEditor.vue'
import ReportPanel from '../../components/ReportPanel.vue'
import Icon from '../../components/Icon.vue'
import StatusPill from '../../components/StatusPill.vue'

const props = defineProps({
  id: { type: Number, required: true },
  tab: { type: String, default: 'plan' },
})

const STEPS = [
  { key: 'plan', title: 'План работ' },
  { key: 'photos', title: 'Снимки и камеры' },
  { key: 'analysis', title: 'Этап и отклонения' },
  { key: 'timeline', title: 'План и факт' },
  { key: 'report', title: 'Отчёт' },
]

const building = ref(null)
const summary = ref(null)
const methodology = ref(null)
const error = ref('')
const version = ref(0)
const stepsEl = ref(null)

function revealStep() {
  nextTick(() => stepsEl.value?.querySelector('.step.active')?.scrollIntoView({ block: 'nearest', inline: 'center' }))
}

const classes = computed(() => (methodology.value?.equipment || []).map((e) => e.cls))
const labels = computed(() => Object.fromEntries((methodology.value?.equipment || []).map((e) => [e.cls, e.label])))
// вкладка «cameras» нового дизайна в классическом — это «Снимки и камеры»
const current = computed(() => (props.tab === 'cameras' ? 'photos' : STEPS.some((s) => s.key === props.tab) ? props.tab : 'plan'))
const kpi = computed(() => summary.value?.timeline_summary)

async function loadBuilding() {
  try {
    building.value = await api.building(props.id)
    Object.assign(ui, { projectId: building.value.project.id, buildingId: props.id })
    error.value = ''
  } catch (e) {
    error.value = e.message
  }
}

async function loadSummary() {
  try {
    summary.value = await api.analysis(props.id)
  } catch {
    summary.value = null
  }
}

function onChanged() {
  version.value += 1
  loadSummary()
  loadBuilding()
  refreshNav()
}

onMounted(async () => {
  methodology.value = await api.methodology().catch(() => null)
  await loadBuilding()
  loadSummary()
  revealStep()
})
watch(() => props.id, () => {
  loadBuilding()
  loadSummary()
})
watch(() => props.tab, () => {
  if (props.tab !== 'plan') loadSummary()
  revealStep()
})
</script>

<template>
  <main class="page">
    <p v-if="error" class="error">{{ error }}</p>
    <template v-if="building">
      <section class="hero" :class="{ bare: !building.cover_photo_id }" aria-label="Объект">
        <div class="cover hero-cover" :class="{ empty: !building.cover_photo_id }">
          <img v-if="building.cover_photo_id" :src="imageUrl(building.cover_photo_id, 1920)" alt="Последний снимок площадки" />
        </div>
        <div class="hero-top">
          <RouterLink :to="`/projects/${building.project.id}`" class="btn small glass">{{ building.project.name }}</RouterLink>
          <span v-if="building.cover_photo_id && summary" class="hero-stamp small"><Icon name="camera" />Кадр {{ formatDateTime(summary.at) }}</span>
        </div>
        <div class="hero-bottom">
          <div class="hero-title">
            <StatusPill v-if="summary" :status="building.photos_count ? summary.verdict.status : ''" glass />
            <h1>{{ building.name }}</h1>
            <p>
              {{ building.object_type_title }}, {{ formatDate(building.start_date) }} — {{ formatDate(building.end_date) }}
              <template v-if="summary && building.photos_count"><br />Фактический этап: {{ summary.verdict.stage.top_name || 'не определён' }}</template>
            </p>
            <RouterLink v-if="!building.photos_count" :to="`/buildings/${id}/photos`" class="btn primary hero-cta">
              <Icon name="upload" />Загрузить снимки или подключить камеру
            </RouterLink>
          </div>
          <div v-if="kpi" class="hero-panel">
            <Gauge :value="kpi.completion_percent" :plan="kpi.planned_percent" :size="128" />
            <dl class="hero-kpi">
              <div><dt>Отставание</dt><dd>{{ kpi.completion_percent === null ? '—' : kpi.max_delay_days }}<small v-if="kpi.completion_percent !== null"> дн.</small></dd><span :class="`risk-${kpi.delay_risk}`">{{ RISK[kpi.delay_risk] }}</span></div>
              <div><dt>Прогноз окончания</dt><dd class="date">{{ formatDate(kpi.forecast_end) }}</dd><span>план {{ formatDate(building.end_date) }}</span></div>
            </dl>
          </div>
        </div>
      </section>

      <nav ref="stepsEl" class="steps" aria-label="Шаги работы с объектом">
        <RouterLink v-for="(s, i) in STEPS" :key="s.key" :to="`/buildings/${id}/${s.key}`" class="step"
          :class="{ active: current === s.key }" :aria-current="current === s.key ? 'step' : undefined">
          <span class="step-num">{{ i + 1 }}</span>{{ s.title }}
        </RouterLink>
      </nav>

      <PlanEditor v-if="current === 'plan'" :key="`plan-${id}`" :building-id="id" @changed="onChanged" />
      <PhotosPanel v-else-if="current === 'photos'" :key="`photos-${id}`" :building="building" :classes="classes" :equipment="methodology?.equipment || []" :phases="methodology?.phases || []" @changed="onChanged" />
      <AnalysisPanel v-else-if="current === 'analysis'" :key="`analysis-${id}-${version}`" :building-id="id"
        :classes="classes" :labels="labels" :activity="methodology?.activity || {}" @changed="loadSummary" />
      <StagesOverview v-else-if="current === 'timeline'" :key="`timeline-${id}-${version}`" :building="building" @changed="onChanged" />
      <ReportPanel v-else :key="`report-${id}`" :building="building" />
    </template>
  </main>
</template>

<style scoped>
.hero { position: relative; min-height: 560px; border-radius: var(--r-xl); overflow: hidden; display: flex; flex-direction: column; justify-content: space-between; box-shadow: var(--shadow); isolation: isolate; }
.hero.bare { min-height: 340px; box-shadow: none; border: 1px solid var(--hair); }
.hero-cover { position: absolute; inset: 0; z-index: -2; }
.hero-cover img { animation: arrive 2.6s var(--ease) both; }
@keyframes arrive { from { transform: scale(1.1); filter: brightness(0.6); } to { transform: scale(1); filter: brightness(1); } }
.hero::after {
  content: ""; position: absolute; inset: 0; z-index: -1; pointer-events: none;
  background:
    linear-gradient(90deg, rgba(10, 14, 16, 0.82) 0%, rgba(10, 14, 16, 0.4) 45%, rgba(10, 14, 16, 0.15) 70%, rgba(10, 14, 16, 0.5) 100%),
    linear-gradient(180deg, rgba(10, 14, 16, 0.5) 0%, rgba(10, 14, 16, 0) 25%, rgba(10, 14, 16, 0) 55%, rgba(10, 14, 16, 0.85) 100%);
}
.hero-top, .hero-bottom { padding: 26px 36px; }
.hero-top { display: flex; justify-content: space-between; align-items: center; gap: 16px; }
.hero-stamp { display: inline-flex; align-items: center; gap: 8px; color: rgba(236, 235, 230, 0.8); }
.hero-stamp svg { width: 15px; height: 15px; }
.hero-bottom { display: flex; justify-content: space-between; align-items: flex-end; gap: 40px; padding-bottom: 36px; }
.hero-title { max-width: 680px; animation: rise 1.2s 0.5s var(--ease) both; }
@keyframes rise { from { opacity: 0; transform: translateY(14px); } }
.hero-cta { margin-top: 24px; }
.hero-title h1 { font-size: 84px; line-height: 0.95; margin: 22px 0 16px; letter-spacing: -0.02em; }
.hero-title p { margin: 0; color: rgba(236, 235, 230, 0.78); font-size: 15px; line-height: 1.65; }
.hero-panel {
  display: flex; align-items: center; gap: 28px; padding: 22px 30px 22px 22px; border-radius: var(--r-l);
  background: rgba(10, 14, 16, 0.5); border: 1px solid rgba(236, 235, 230, 0.12);
  backdrop-filter: blur(20px) saturate(1.1); -webkit-backdrop-filter: blur(20px) saturate(1.1);
  animation: rise 1.2s 0.7s var(--ease) both;
}
.hero-kpi { display: grid; gap: 16px; margin: 0; }
.hero-kpi > div { display: grid; }
.hero-kpi > div + div { padding-top: 16px; border-top: 1px solid rgba(236, 235, 230, 0.12); }
.hero-kpi dt { font-size: 12px; color: rgba(236, 235, 230, 0.6); }
.hero-kpi dd { margin: 2px 0 1px; font-family: var(--serif); font-size: 38px; line-height: 1; font-variant-numeric: lining-nums; }
.hero-kpi dd small { font-size: 18px; }
.hero-kpi dd.date { font-size: 28px; line-height: 1.2; }
.hero-kpi span { font-size: 12px; color: rgba(236, 235, 230, 0.6); }
.risk-unknown { color: var(--ink-3) !important; }
.risk-high { color: var(--critical) !important; } .risk-medium { color: var(--warning) !important; } .risk-low { color: var(--ok) !important; }
.steps { display: flex; gap: 36px; margin: 8px 0 36px; border-bottom: 1px solid var(--hair); overflow-x: auto; scrollbar-width: none; }
.step { position: relative; display: flex; align-items: center; gap: 10px; white-space: nowrap; padding: 20px 0 18px; text-decoration: none; color: var(--ink-3); font-size: 14px; transition: color 0.25s; }
.step::after { content: ""; position: absolute; left: 0; right: 0; bottom: -1px; height: 1.5px; background: var(--accent); transform: scaleX(0); transform-origin: left; transition: transform 0.45s var(--ease); }
.step:hover { color: var(--ink-2); }
.step.active { color: var(--ink); }
.step.active::after { transform: scaleX(1); }
.step-num { font-family: var(--serif); font-size: 17px; color: var(--ink-3); font-variant-numeric: lining-nums; }
.step.active .step-num { color: var(--accent); }
@media (max-width: 1100px) {
  .hero { min-height: 0; }
  .hero-top, .hero-bottom { padding: 20px; }
  .hero-stamp { display: none; }
  .hero::after { background: linear-gradient(180deg, rgba(10, 14, 16, 0.3) 0%, rgba(10, 14, 16, 0.75) 40%, rgba(10, 14, 16, 0.94) 100%); }
  .hero-bottom { flex-direction: column; align-items: stretch; padding-top: 110px; gap: 24px; }
  .hero-title h1 { font-size: 48px; }
  .hero-panel { padding: 18px; gap: 20px; }
  .steps { gap: 24px; margin-bottom: 24px; }
}
</style>
