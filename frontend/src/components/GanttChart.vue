<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { api } from '../api.js'
import { formatDate, formatDateTime, toLocalInput } from '../lib/format.js'
import { makeScale, monthTicks, bar } from '../lib/gantt.js'
import { OBSERVABILITY, PCT, RISK, timelineColor } from '../lib/labels.js'
import { useRouter } from 'vue-router'

const router = useRouter()

function openPhase(phaseId) {
  router.push({
    name: 'phase',
    params: {
      buildingId: props.buildingId,
      phaseId
    }
  })
}
const props = defineProps({ buildingId: { type: Number, required: true } })

const tl = ref(null)
const at = ref('')
const error = ref('')
const expanded = reactive({})
const W = 1000

// Hover по таймлайну
const hoverX = ref(null)
const hoverDate = ref(null)

const scale = computed(() => tl.value && makeScale(tl.value.start, tl.value.end, W))
const ticks = computed(() => tl.value ? monthTicks(tl.value.start, tl.value.end, W, 46) : [])
const nowX = computed(() => tl.value ? Math.min(W, Math.max(0, scale.value.x(tl.value.at))) / 10 : 0)

const usedStatuses = computed(() => {
  if (!tl.value) return []

  const used = new Set(
    tl.value.rows.flatMap((r) => [
      r.status,
      ...r.tasks.map((t) => t.status)
    ])
  )

  return tl.value.legend.filter((l) => used.has(l.status))
})

function pos(start, end) {
  const b = bar(scale.value, start, end)

  return {
    left: b.x / 10 + '%',
    width: b.w / 10 + '%'
  }
}

/**
 * Преобразует положение мыши в дату.
 *
 * x — процент от 0 до 100 внутри временной шкалы.
 */
function dateFromX(x) {
  if (!tl.value) return null

  const start = new Date(tl.value.start).getTime()
  const end = new Date(tl.value.end).getTime()

  const ratio = Math.max(0, Math.min(1, x / 100))

  return new Date(start + (end - start) * ratio)
}

/**
 * Наведение на весь Gantt.
 */
function onGanttMove(event) {
  const gantt = event.currentTarget

  // Берём именно область графика, а не левую колонку с названиями.
  const track = gantt.querySelector('.g-head .g-track')

  if (!track) return

  const rect = track.getBoundingClientRect()

  const x = event.clientX - rect.left

  const percent = Math.max(
    0,
    Math.min(100, (x / rect.width) * 100)
  )

  hoverX.value = percent
  hoverDate.value = dateFromX(percent)
}

function onGanttLeave() {
  hoverX.value = null
  hoverDate.value = null
}

async function load() {
  error.value = ''

  try {
    tl.value = await api.timeline(props.buildingId, at.value)

    if (!at.value) {
      at.value = toLocalInput(tl.value.at)
    }
  } catch (e) {
    error.value = e.message
  }
}

onMounted(load)
</script>

<template>
  <section class="stack">
    <div class="toolbar">
      <label class="field inline">Статусы на<input v-model="at" type="datetime-local" /></label>
      <button class="btn" type="button" @click="load">Показать</button>
    </div>
    <p v-if="error" class="error" role="alert">{{ error }}</p>

    <div v-if="tl" class="panel">
      <!-- <div class="panel-head">
        <div>
          <h2>Таймлайн этапов</h2>
          <p class="muted small">Полоса — срок по плану, цвет — статус на {{ formatDateTime(tl.at) }}, точки — дни, подтверждённые снимками.</p>
          <p v-if="!tl.observed" class="small hint">Снимков ещё нет: показан только план, выполнение не оценивается.</p>
        </div>
        <span class="status" :class="{ high: 'critical', medium: 'warning', low: 'ok' }[tl.delay_risk]">{{ RISK[tl.delay_risk] }}</span>
      </div> -->
      <!-- <div class="kpi-row summary">
        <div class="kpi"><b>{{ PCT(tl.completion_percent) }}</b><span>готовность по факту</span></div>
        <div class="kpi"><b>{{ tl.planned_percent }}%</b><span>по графику</span></div>
        <div class="kpi"><b>{{ tl.spi ?? '—' }}</b><span>индекс выполнения графика</span></div>
        <div class="kpi"><b>{{ tl.observed ? tl.max_delay_days : '—' }}</b><span>дней отставания</span></div>
        <div class="kpi"><b class="date">{{ formatDate(tl.forecast_end) }}</b><span>прогноз, план {{ formatDate(tl.end) }}</span></div>
      </div>
 -->
      <div v-if="!tl.rows.length" class="empty"><p>В плане нет активных работ.</p></div>
      <div
          v-else
          class="gantt"
          role="table"
          aria-label="Таймлайн этапов"
          @mousemove="onGanttMove"
          @mouseleave="onGanttLeave"
        >
        
        <div class="g-row g-head" role="row">
          <div class="g-name" role="columnheader"></div>
          <div class="g-track" role="columnheader">
            <span v-for="(t, i) in ticks" :key="i" class="tick" :class="{ year: t.year }" :style="{ left: t.x / 10 + '%' }"><em>{{ t.label }}</em></span>
            <span class="now-label" :style="{ left: nowX + '%' }">сейчас</span>
          </div>
        </div>
        <template v-for="r in tl.rows" :key="r.phase">
          <div
            class="g-row phase-row"
            role="row"
            @click="openPhase(r.phase)"
          >
            <div class="g-name" role="cell">
              <!-- <button class="expand" type="button" :aria-expanded="Boolean(expanded[r.phase])" :aria-label="`Работы этапа ${r.name}`"
                @click="expanded[r.phase] = !expanded[r.phase]">{{ expanded[r.phase] ? '−' : '+' }}</button> -->
              <div class="g-label">
                <span class="nm">{{ r.name }}</span>
                <!-- <span class="small st"><span class="swatch" :style="{ background: timelineColor(r.status, r.color) }"></span>{{ r.status_label }}{{ r.delay_days ? `, ${r.delay_days} дн.` : '' }}</span> -->
              </div>
            </div>
            <div class="g-track" role="cell">
              <span v-for="(t, i) in ticks" :key="i" class="grid" :class="{ year: t.year }" :style="{ left: t.x / 10 + '%' }"></span>
              <span class="bar" :class="{ hatched: r.observability === 'none' || r.observability === 'low' }"
                :style="{ ...pos(r.start, r.end), background: timelineColor(r.status, r.color) }"
                :title="`${r.name}: ${formatDate(r.start)} — ${formatDate(r.end)}. ${OBSERVABILITY[r.observability]}`"></span>
              <span v-for="e in r.evidence" :key="e.date" class="dot" :style="{ left: scale.x(e.date) / 10 + '%' }"
                :title="`${formatDate(e.date)}: ${e.photos} сним.`"></span>
              <span class="now" :style="{ left: nowX + '%' }"></span>
            </div>
          </div>
          <!-- <template v-if="expanded[r.phase]">
            <div v-for="t in r.tasks" :key="t.code" class="g-row sub" role="row">
              <div class="g-name" role="cell"><span class="small sub-name">{{ t.name }}</span></div>
              <div class="g-track" role="cell">
                <span class="bar thin" :style="{ ...pos(t.start, t.end), background: timelineColor(t.status, t.color) }" :title="`${formatDate(t.start)} — ${formatDate(t.end)}`"></span>
                <span class="now" :style="{ left: nowX + '%' }"></span>
              </div>
            </div>
          </template> -->
        </template>
      </div>

      <div class="legend small">
        <span v-for="l in usedStatuses" :key="l.status"><span class="swatch" :style="{ background: timelineColor(l.status, l.color) }"></span>{{ l.label }}</span>
        <span><span class="swatch hatched-sw"></span>не видно камерам, статус по срокам</span>
        <span><span class="dot-sw"></span>подтверждено снимками</span>
      </div>
    </div>
  </section>
</template>

<style scoped>
.toolbar { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }
.field.inline { display: flex; align-items: center; gap: 12px; }
.hint { color: var(--accent); margin: 6px 0 0; }
.summary { padding: 8px 0 28px; margin-bottom: 8px; border-bottom: 1px solid var(--hair); }
.kpi b.date { font-size: 32px; line-height: 1.5; }
.gantt { overflow-x: auto; }
.g-row { display: grid; grid-template-columns: 300px minmax(620px, 1fr); min-height: 58px; }
.g-row + .g-row { border-top: 1px solid var(--hair); }
.g-row.sub { min-height: 34px; background: rgba(236, 235, 230, 0.02); border-top-color: rgba(236, 235, 230, 0.04); }
.g-head { min-height: 60px; }
.g-name { display: flex; gap: 14px; align-items: center; padding: 8px 18px 8px 0; min-width: 0; }
.g-row.sub .g-name { padding-left: 42px; }
.g-label { display: grid; min-width: 0; }
.nm { font-size: 14px; }
.phase-row {
  cursor: pointer;
}

.phase-row:hover {
  background: rgba(236, 235, 230, 0.04);
}
.st { display: flex; align-items: center; gap: 7px; color: var(--ink-3); }
.sub-name { color: var(--ink-3); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.expand { width: 28px; height: 28px; flex: none; border: 1px solid var(--hair-2); background: transparent; border-radius: 50%; cursor: pointer; font: inherit; color: var(--ink-2); transition: border-color 0.2s; }
.expand:hover { border-color: var(--accent); color: var(--accent); }
.g-track { position: relative; }
.tick { position: absolute; top: 0; bottom: 0; }
.tick em { position: absolute; bottom: 8px; left: 7px; font-style: normal; font-size: 12px; color: var(--ink-3); white-space: nowrap; }
.tick.year em { font-family: var(--serif); font-size: 17px; color: var(--ink); bottom: 5px; }
.grid { position: absolute; top: 0; bottom: 0; border-left: 1px solid rgba(236, 235, 230, 0.035); }
.grid.year { border-left-color: var(--hair-2); }
.bar { position: absolute; top: 24px; height: 10px; border-radius: 5px; }
.bar.thin { top: 14px; height: 5px; border-radius: 3px; opacity: 0.85; }
.bar.hatched { background-image: repeating-linear-gradient(-45deg, rgba(13, 18, 21, 0.45) 0 3px, transparent 3px 7px) !important; }
.dot { position: absolute; top: 24px; width: 10px; height: 10px; margin-left: -5px; border-radius: 50%; background: var(--night); border: 2px solid var(--ink); }
.now { position: absolute; top: 0; bottom: 0; width: 0; border-left: 1px solid var(--accent); }
.now-label { position: absolute; top: 6px; transform: translateX(-50%); padding: 2px 10px; border-radius: 999px; background: var(--accent); color: var(--accent-ink); font-size: 11.5px; font-weight: 500; white-space: nowrap; }
.legend { display: flex; flex-wrap: wrap; gap: 10px 24px; margin-top: 22px; padding-top: 18px; border-top: 1px solid var(--hair); color: var(--ink-3); }
.legend > span { display: inline-flex; align-items: center; gap: 8px; }
.hatched-sw { background: repeating-linear-gradient(-45deg, var(--ink-3) 0 3px, transparent 3px 6px); }
.dot-sw { width: 10px; height: 10px; border-radius: 50%; border: 2px solid var(--ink); }
</style>
