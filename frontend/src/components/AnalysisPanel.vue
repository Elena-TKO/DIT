<script setup>
import { computed, onMounted, ref } from 'vue'
import { api, imageUrl } from '../api.js'
import { formatDate, formatDateTime, money, toLocalInput } from '../lib/format.js'
import { OBSERVABILITY, PCT, RISK } from '../lib/labels.js'
import Icon from './Icon.vue'
import Sparkline from './Sparkline.vue'
import PhotoInspector from './PhotoInspector.vue'
import StatusPill from './StatusPill.vue'

const props = defineProps({
  buildingId: { type: Number, required: true },
  classes: { type: Array, default: () => [] },
  labels: { type: Object, default: () => ({}) },
  activity: { type: Object, default: () => ({}) },
})
const emit = defineEmits(['changed'])

const data = ref(null)
const at = ref('')
const error = ref('')
const busy = ref(false)
const saved = ref(false)
const openId = ref(null)
const trend = ref(null)

const verdict = computed(() => data.value?.verdict)
const kpi = computed(() => data.value?.timeline_summary)
const econ = computed(() => data.value?.economics)
const idleLimit = computed(() => props.activity?.idle_alert_minutes || 60)
const topRanking = computed(() => (verdict.value?.stage.ranking || []).filter((r) => r.score > 0).slice(0, 5))
const label = (cls) => props.labels[cls] || cls
const STATUS_ICON = { ok: 'check', warning: 'alert', critical: 'alert' }
const SEVERITY_ICON = { critical: 'alert', warning: 'alert', info: 'clock' }
const PRIORITY = { high: 'Срочно', medium: 'Важно', low: 'К сведению' }

async function load(save = false) {
  busy.value = true
  error.value = ''
  try {
    data.value = save ? await api.runAnalysis(props.buildingId, at.value) : await api.analysis(props.buildingId, at.value)
    if (!at.value) at.value = toLocalInput(data.value.at)
    saved.value = save
    if (save) {
      emit('changed')
      loadTrend()
    }
  } catch (e) {
    error.value = e.message
  } finally {
    busy.value = false
  }
}

async function loadTrend() {
  trend.value = await api.history(props.buildingId).catch(() => null)
}

onMounted(() => {
  load()
  loadTrend()
})
</script>

<template>
  <section class="stack">
    <div class="toolbar">
      <label class="field inline">Состояние на<input v-model="at" type="datetime-local" /></label>
      <button class="btn" type="button" :disabled="busy" @click="load(false)">Показать</button>
      <span class="faint small grow">По умолчанию — время последнего снимка; окно анализа {{ verdict?.window_hours || 24 }} ч</span>
      <span v-if="saved" class="small saved"><Icon name="check" />Записано в журнал</span>
      <button class="btn primary" type="button" :disabled="busy || (verdict && !verdict.observed)"
        :title="verdict && !verdict.observed ? 'Пока нет снимков, записывать в журнал нечего' : ''"
        @click="load(true)">Записать в журнал</button>
    </div>
    <p v-if="error" class="error" role="alert">{{ error }}</p>

    <template v-if="verdict">
      <div class="panel verdict">
        <div class="verdict-main">
          <span class="verdict-icon" :class="verdict.status"><Icon :name="STATUS_ICON[verdict.status]" /></span>
          <div>
            <div class="verdict-meta"><StatusPill :status="verdict.status" /><span class="faint small">на {{ formatDateTime(data.at) }}, {{ verdict.photos_in_window }} сним. в окне</span></div>
            <p class="verdict-text">{{ verdict.summary }}</p>
          </div>
        </div>
        <div class="kpi-row">
          <div class="kpi"><b>{{ PCT(kpi.completion_percent) }}</b><span>готовность по факту</span></div>
          <div class="kpi"><b>{{ kpi.planned_percent }}%</b><span>должно быть по графику</span></div>
          <div class="kpi"><b>{{ kpi.completion_percent === null ? '—' : kpi.max_delay_days }}</b><span>дней отставания</span></div>
          <div class="kpi"><b class="date">{{ formatDate(kpi.forecast_end) }}</b><span>{{ RISK[kpi.delay_risk] }}</span></div>
        </div>
      </div>

      <div v-if="econ && econ.photos_in_window" class="panel losses">
        <div class="panel-head">
          <div>
            <h3>Во что обходится отклонение</h3>
            <p class="faint small">
              {{ econ.note }} Считается только измеренный простой: дни отставания в рубли не переводятся.
            </p>
          </div>

        </div>
        <div class="loss-grid">
          <div class="loss-main">
            <span class="faint small">Простой техники за окно анализа</span>
            <b class="serif" :class="{ zero: !econ.idle_total }">
              {{ econ.idle_measurable ? money(econ.idle_total, econ.currency) : '—' }}
            </b>
            <span v-if="econ.idle_total" class="faint small">
              {{ Math.round(econ.idle_minutes / 60 * 10) / 10 }} ч техника стояла на месте
            </span>
            <span v-else-if="econ.idle_measurable" class="faint small">
              Простоя дольше {{ idleLimit }} мин не зафиксировано
            </span>
            <span v-else class="small hint">
              Снимки загружены без камеры — простой по ним не определяется. Выберите камеру при загрузке
              или подключите её на шаге «Снимки и камеры», и потери появятся здесь.
            </span>
          </div>
          <ul v-if="econ.idle_total" class="loss-list small">
            <li v-for="e in econ.by_equipment" :key="e.cls">
              <span>{{ e.label }}</span>
              <span class="faint">{{ e.minutes }} мин</span>
              <span class="loss-cell">{{ money(e.cost, econ.currency) }}</span>
            </li>
          </ul>
          <p v-else class="faint small">
            Простой считается так: если рамка одной и той же техники не сдвинулась в соседних кадрах одной
            камеры, время между кадрами засчитывается как простой и умножается на часовую ставку из методики.
          </p>
        </div>
        <p class="loss-note small faint">
          Отставание графика — {{ econ.delay_days }} дн. В рубли не переводится: техника в эти дни не простаивает
          под счётчик. Для ориентира: день работы замеченной на объекте техники
          ({{ econ.fleet.join(', ') }}) обходится примерно в {{ money(econ.daily_fleet_cost, econ.currency) }}.
        </p>
      </div>

      <div v-if="trend" class="panel trend">
        <div class="panel-head">
          <div>
            <h3>Динамика</h3>
            <p class="faint small">По вердиктам, записанным в журнал: сплошная — факт, пунктир — план.</p>
          </div>
          <span v-if="trend.change_percent !== null" class="trend-delta serif"
            :class="trend.change_percent >= 0 ? 'up' : 'down'">
            {{ trend.change_percent >= 0 ? '+' : '' }}{{ trend.change_percent }}%
          </span>
        </div>
        <Sparkline :points="trend.points" />
      </div>

      <div class="grid-2">
        <div class="panel">
          <h3>Фактический этап</h3>
          <p class="stage-text">{{ verdict.stage.explanation }}</p>
          <ul v-if="topRanking.length" class="ranking">
            <li v-for="r in topRanking" :key="r.phase" :class="{ confirmed: r.confirmed }">
              <div class="rank-head">
                <span>{{ r.name }}</span>
                <span class="small" :class="r.confirmed ? 'ok-text' : 'faint'">{{ Math.round(r.score * 100) }}</span>
              </div>
              <div class="progress"><i :style="{ width: r.score * 100 + '%' }"></i></div>
              <span class="faint small">
                {{ r.confirmed ? 'Обязательная техника на месте' : `Не хватает: ${r.missing_groups.map((g) => g.map(label).join(' или ')).join('; ')}` }}
              </span>
            </li>
          </ul>
        </div>

        <div class="panel">
          <h3>Техника в окне анализа</h3>
          <p v-if="!verdict.equipment.length" class="faint">Техника на снимках не обнаружена.</p>
          <ul v-else class="equipment">
            <li v-for="e in verdict.equipment" :key="e.cls">
              <div>
                <b>{{ e.label }}</b>
                <span class="faint small">{{ e.zones.join(', ') || 'зона не указана' }}; до {{ e.max_count }} одновременно</span>
              </div>
              <div class="eq-count">
                <span class="small">{{ e.photos }} сним.</span>
                <span class="small" :class="e.idle ? 'warn-text' : 'faint'">{{ e.working }} работает, {{ e.idle }} стоит</span>
              </div>
            </li>
          </ul>
        </div>
      </div>

      <div class="panel">
        <div class="panel-head">
          <h3>Что есть и чего нет по графику</h3>
          <span class="faint small">Методика «этап → техника»</span>
        </div>
        <p v-if="!verdict.checklist.length" class="faint">На эту дату по плану нет работ.</p>
        <div v-for="c in verdict.checklist" :key="c.phase" class="check">
          <div class="check-name">
            <b>{{ c.name }}</b>
            <span class="faint small">{{ OBSERVABILITY[c.observability] }}</span>
          </div>
          <div class="check-body">
            <div class="chips">
              <span v-if="!c.required.length" class="faint small">{{ c.hint }}</span>
              <span v-for="(g, i) in c.required" :key="i" class="tag" :class="g.present ? 'present' : 'absent'">
                <Icon :name="g.present ? 'check' : 'alert'" class="tag-icon" />{{ g.present ? g.seen.map(label).join(', ') : g.labels.join(' или ') }}
              </span>
              <span v-for="cls in c.typical_present" :key="'t' + cls" class="tag">{{ label(cls) }}</span>
              <span v-for="cls in c.unexpected_present" :key="'u' + cls" class="tag extra">нетипично: {{ label(cls) }}</span>
            </div>
            <p class="faint small">
              {{ c.tasks.map((t) => t.name).slice(0, 3).join('; ') }}{{ c.tasks_total > 3 ? ` и ещё ${c.tasks_total - 3}` : '' }}
            </p>
          </div>
        </div>
      </div>

      <div class="grid-2">
        <div class="panel">
          <div class="panel-head">
            <h3>Отклонения</h3>
            <span class="faint small">{{ verdict.deviations.length }}</span>
          </div>
          <p v-if="!verdict.deviations.length" class="faint">Отклонений не выявлено.</p>
          <article v-for="(d, i) in verdict.deviations" :key="i" class="dev">
            <span class="dev-icon" :class="d.severity"><Icon :name="SEVERITY_ICON[d.severity]" /></span>
            <div class="dev-body">
              <div class="dev-head">
                <b>{{ d.title }}</b>
                <span class="faint small">{{ d.severity_label }}{{ d.zones.length ? `, ${d.zones.join(', ')}` : '' }}</span>
              </div>
              <p class="small">{{ d.message }}</p>
              <div v-if="d.photo_ids.length" class="thumbs">
                <button v-for="pid in d.photo_ids.slice(-4)" :key="pid" type="button" :aria-label="`Открыть снимок ${pid}`"
                  @click="openId = pid"><img :src="imageUrl(pid, 240)" alt="" loading="lazy" /></button>
              </div>
            </div>
          </article>
        </div>
        <div class="panel">
          <h3>Рекомендации</h3>
          <p v-if="!data.recommendations.length" class="faint">Действий не требуется.</p>
          <ol class="recs">
            <li v-for="(r, i) in data.recommendations" :key="i">
              <span class="rec-priority small" :class="r.priority">{{ PRIORITY[r.priority] || r.priority }}</span>
              <span>{{ r.text }}</span>
            </li>
          </ol>
        </div>
      </div>
    </template>

    <PhotoInspector v-if="openId" :photo-id="openId" :classes="classes" @close="openId = null" @changed="load(false)" />
  </section>
</template>

<style scoped>
.toolbar { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }
.field.inline { display: flex; align-items: center; gap: 12px; }
.grow { flex: 1; }
.saved { display: inline-flex; align-items: center; gap: 7px; color: var(--ok); }
.saved svg { width: 16px; height: 16px; }
.verdict { padding: 36px; }
.verdict-main { display: grid; grid-template-columns: 60px 1fr; gap: 24px; align-items: start; padding-bottom: 30px; margin-bottom: 28px; border-bottom: 1px solid var(--hair); }
.verdict-icon { width: 60px; height: 60px; border-radius: 50%; display: grid; place-items: center; border: 1px solid; }
.verdict-icon svg { width: 26px; height: 26px; }
.verdict-icon.ok { color: var(--ok); border-color: rgba(140, 195, 157, 0.35); background: var(--ok-soft); }
.verdict-icon.warning { color: var(--warning); border-color: rgba(240, 165, 83, 0.35); background: var(--warning-soft); }
.verdict-icon.critical { color: var(--critical); border-color: rgba(238, 122, 103, 0.35); background: var(--critical-soft); }
.verdict-meta { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; margin-bottom: 12px; }
.verdict-text { font-family: var(--serif); font-size: 34px; line-height: 1.18; font-weight: 400; margin: 0; max-width: 34ch; }
.kpi b.date { font-size: 34px; line-height: 1.45; }
.hint { color: var(--accent); }
.trend-delta { font-size: 26px; }
.trend-delta.up { color: var(--ok); }
.trend-delta.down { color: var(--critical); }
.losses { border-color: rgba(205, 183, 143, 0.25); }
.loss-grid { display: grid; grid-template-columns: minmax(220px, 0.8fr) 1.2fr; gap: 36px; align-items: start; }
.loss-main { display: grid; gap: 6px; }
.loss-main b.zero { color: var(--ink-3); }
.loss-main b { font-size: 44px; font-weight: 400; color: var(--accent); line-height: 1.05; }
.loss-list { list-style: none; margin: 0; padding: 0; }
.loss-list li { display: grid; grid-template-columns: 1fr auto 120px; gap: 16px; padding: 10px 0; border-top: 1px solid var(--hair); }
.loss-list li:first-child { border-top: 0; padding-top: 0; }
.loss-cell { text-align: right; }
.loss-note { margin: 18px 0 0; padding-top: 16px; border-top: 1px solid var(--hair); max-width: none; }
.panel h3 { margin-bottom: 12px; }
.panel-head h3 { margin-bottom: 0; }
.stage-text { color: var(--ink-2); }
.ranking, .equipment, .recs { list-style: none; margin: 0; padding: 0; }
.ranking li { display: grid; gap: 8px; padding: 14px 0; border-top: 1px solid var(--hair); }
.rank-head { display: flex; justify-content: space-between; font-size: 14px; }
.rank-head .small { font-family: var(--serif); font-size: 20px; line-height: 1; }
.ranking .progress > i { background: var(--ink-3); }
.ranking li.confirmed .progress > i { background: var(--ok); }
.ok-text { color: var(--ok); } .warn-text { color: var(--warning); }
.equipment li { display: flex; justify-content: space-between; gap: 16px; padding: 14px 0; border-top: 1px solid var(--hair); }
.equipment li:first-child { border-top: 0; padding-top: 4px; }
.equipment b { display: block; font-weight: 500; }
.eq-count { display: grid; text-align: right; }
.check { display: grid; grid-template-columns: 280px 1fr; gap: 28px; padding: 16px 0; border-top: 1px solid var(--hair); }
.check-name { display: grid; align-content: start; gap: 2px; }
.check-name b { font-weight: 500; }
.chips { display: flex; flex-wrap: wrap; gap: 7px; margin-bottom: 8px; }
.tag-icon { width: 13px; height: 13px; }
.check-body p { margin: 0; }
.dev { display: grid; grid-template-columns: 38px 1fr; gap: 16px; padding: 18px 0; border-top: 1px solid var(--hair); }
.dev:first-of-type { border-top: 0; padding-top: 0; }
.dev-icon { width: 38px; height: 38px; border-radius: 50%; display: grid; place-items: center; border: 1px solid; }
.dev-icon svg { width: 17px; height: 17px; }
.dev-icon.critical { color: var(--critical); border-color: rgba(238, 122, 103, 0.35); }
.dev-icon.warning { color: var(--warning); border-color: rgba(240, 165, 83, 0.35); }
.dev-icon.info { color: var(--info); border-color: rgba(147, 182, 214, 0.35); }
.dev-head { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 4px 12px; margin-bottom: 6px; }
.dev-head b { font-weight: 500; }
.dev-body p { margin: 0; color: var(--ink-2); }
.thumbs { display: flex; gap: 8px; margin-top: 12px; flex-wrap: wrap; }
.thumbs button { padding: 0; border: 1px solid var(--hair); background: var(--panel-2); border-radius: var(--r-s); overflow: hidden; cursor: zoom-in; }
.thumbs img { width: 112px; height: 74px; object-fit: cover; display: block; transition: transform 0.6s var(--ease); }
.thumbs button:hover img { transform: scale(1.06); }
.recs li { display: grid; grid-template-columns: 96px 1fr; gap: 16px; padding: 14px 0; border-top: 1px solid var(--hair); }
.recs li:first-child { border-top: 0; padding-top: 4px; }
.rec-priority { align-self: start; color: var(--ink-3); }
.rec-priority::before { content: ""; display: inline-block; width: 6px; height: 6px; border-radius: 50%; background: currentColor; margin-right: 8px; vertical-align: 2px; }
.rec-priority.high { color: var(--critical); }
.rec-priority.medium { color: var(--warning); }
@media (max-width: 900px) {
  .grow { flex-basis: 100%; order: 3; }
  .check { grid-template-columns: 1fr; gap: 8px; }
  .verdict { padding: 22px; }
  .verdict-text { font-size: 26px; }
  .loss-grid { grid-template-columns: 1fr; }
}
</style>
