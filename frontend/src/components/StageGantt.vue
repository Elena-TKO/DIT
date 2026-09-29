<script setup>
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { formatDate } from '../lib/format.js'
import { dateAt, inRange, monthTicks, pct } from '../lib/gantt.js'
import Icon from './Icon.vue'

// Гант этапов: план — полупрозрачная плашка с контуром, факт — яркая плашка по датам проанализированных
// снимков этапа, камера — отметка дня со снимками. Линия «Сегодня» и линия под курсором с датой.
const props = defineProps({
  stages: { type: Array, default: () => [] },
  start: { type: String, required: true },
  end: { type: String, required: true },
  today: { type: String, default: '' },
  buildingId: { type: Number, required: true },
})

const PALETTE = ['#4f7cf7', '#2f9e67', '#e0892b', '#7c5cfc', '#d4557a', '#1c9a96', '#b08a2e', '#5b8def']
const router = useRouter()
const body = ref(null)
const hover = ref(null)          // { left: %, date }

const ticks = computed(() => monthTicks(props.start, props.end, 1000, 55).map((t) => ({ ...t, left: t.x / 10 })))
const todayLeft = computed(() => (props.today && inRange(props.start, props.end, props.today)
  ? pct(props.start, props.end, props.today).left : null))
const rows = computed(() => props.stages.map((s, i) => ({
  ...s,
  hue: PALETTE[i % PALETTE.length],
  plan: s.start && s.end ? pct(props.start, props.end, s.start, s.end) : null,
  fact: s.photo_start ? pct(props.start, props.end, s.photo_start, s.photo_end || s.photo_start) : null,
  marks: (s.photo_days || []).filter((d) => inRange(props.start, props.end, d.date))
    .map((d) => ({ ...d, left: pct(props.start, props.end, d.date).left })),
})))

function track() {
  return body.value?.querySelector('.sg-overlay')?.getBoundingClientRect()
}

function onMove(event) {
  const rect = track()
  if (!rect || event.clientX < rect.left || event.clientX > rect.right) {
    hover.value = null
    return
  }
  const f = (event.clientX - rect.left) / rect.width
  hover.value = { left: f * 100, date: dateAt(props.start, props.end, f), flip: f > 0.82 }
}

function openStage(phase) {
  router.push(`/buildings/${props.buildingId}/stages/${phase}`)
}
</script>

<template>
  <div class="sg">
    <div class="sg-legend">
      <span><i class="sg-key plan"></i>План</span>
      <span><i class="sg-key fact"></i>Факт по снимкам</span>
      <span><Icon name="camera" />Загружены снимки</span>
      <span><i class="sg-key today"></i>Сегодня</span>
      <span class="sg-hint">Наведите на шкалу — покажу дату</span>
    </div>
    <div class="sg-scroll">
      <div ref="body" class="sg-body" @mousemove="onMove" @mouseleave="hover = null">
        <div class="sg-row sg-head">
          <span class="sg-label"></span>
          <div class="sg-track">
            <span v-for="(t, i) in ticks" :key="i" class="sg-tick" :class="{ year: t.year }" :style="{ left: t.left + '%' }">{{ t.label }}</span>
          </div>
        </div>
        <div v-for="r in rows" :key="r.phase" class="sg-row">
          <button type="button" class="sg-label" :title="`Открыть этап «${r.name}»`" @click="openStage(r.phase)">
            <b>{{ r.name }}</b>
            <small>
              <template v-if="r.photos"><Icon name="camera" />{{ r.photos }}</template>
              <template v-if="r.status_label"> · {{ r.status_label }}</template>
            </small>
          </button>
          <div class="sg-track">
            <i v-for="(t, i) in ticks" :key="i" class="sg-grid" :style="{ left: t.left + '%' }"></i>
            <span v-if="r.plan" class="sg-plan" :style="{ left: r.plan.left + '%', width: r.plan.width + '%', '--hue': r.hue }"
              :title="`План: ${formatDate(r.start)} — ${formatDate(r.end)}`"></span>
            <span v-if="r.fact" class="sg-fact" :style="{ left: r.fact.left + '%', width: r.fact.width + '%', '--hue': r.hue }"
              :title="`Факт по снимкам: ${formatDate(r.photo_start)} — ${formatDate(r.photo_end)}`"></span>
            <button v-for="m in r.marks" :key="m.date" type="button" class="sg-mark" :style="{ left: m.left + '%', '--hue': r.hue }"
              :title="`${formatDate(m.date)}: ${m.photos} сним. — открыть этап`" :aria-label="`Снимки ${formatDate(m.date)}`"
              @click="openStage(r.phase)"><Icon name="camera" /></button>
          </div>
        </div>
        <div class="sg-overlay" aria-hidden="true">
          <div v-if="todayLeft !== null" class="sg-today" :style="{ left: todayLeft + '%' }"><span>Сегодня</span></div>
          <div v-if="hover" class="sg-cursor" :class="{ flip: hover.flip }" :style="{ left: hover.left + '%' }"><span>{{ formatDate(hover.date) }}</span></div>
        </div>
      </div>
    </div>
    <p v-if="!stages.length" class="sg-empty">Этапы ещё не сформированы — проверьте план работ.</p>
  </div>
</template>

<style>
.sg { --sg-label: 250px; --sg-line: var(--hair); color: var(--ink); }
.sg-legend { display: flex; flex-wrap: wrap; gap: 18px; align-items: center; font-size: 12px; color: var(--ink-3); margin-bottom: 14px; }
.sg-legend span { display: inline-flex; align-items: center; gap: 6px; }
.sg-legend svg { width: 14px; height: 14px; color: var(--accent); }
.sg-hint { margin-left: auto; }
.sg-key { display: inline-block; width: 22px; height: 10px; border-radius: 3px; }
.sg-key.plan { background: color-mix(in srgb, #4f7cf7 20%, transparent); border: 1.5px solid #4f7cf7; }
.sg-key.fact { background: #4f7cf7; }
.sg-key.today { width: 2px; height: 14px; background: #d4557a; border-radius: 1px; }
.sg-scroll { overflow-x: auto; }
.sg-body { position: relative; min-width: 820px; }
.sg-row { display: grid; grid-template-columns: var(--sg-label) minmax(0, 1fr); align-items: center; min-height: 44px; border-top: 1px solid var(--sg-line); }
.sg-head { min-height: 28px; border-top: 0; }
.sg-label { display: grid; gap: 1px; text-align: left; background: none; border: 0; padding: 6px 14px 6px 0; font: inherit; color: inherit; cursor: pointer; min-width: 0; }
.sg-head .sg-label { cursor: default; }
.sg-label b { font-size: 13px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sg-label small { display: inline-flex; align-items: center; gap: 4px; font-size: 11px; color: var(--ink-3); }
.sg-label small svg { width: 12px; height: 12px; }
.sg-label:hover b { color: var(--accent); }
.sg-track { position: relative; height: 44px; }
.sg-head .sg-track { height: 28px; }
.sg-tick { position: absolute; top: 6px; transform: translateX(-50%); font-size: 11px; color: var(--ink-3); white-space: nowrap; }
.sg-tick.year { font-weight: 700; color: var(--ink-2, var(--ink)); }
.sg-grid { position: absolute; top: 0; bottom: 0; width: 1px; background: var(--sg-line); }
.sg-plan { position: absolute; top: 9px; height: 26px; border-radius: 6px; background: color-mix(in srgb, var(--hue) 16%, transparent); border: 1.5px dashed color-mix(in srgb, var(--hue) 70%, transparent); box-sizing: border-box; }
.sg-fact { position: absolute; top: 15px; height: 14px; border-radius: 4px; background: var(--hue); box-shadow: 0 2px 8px color-mix(in srgb, var(--hue) 45%, transparent); }
.sg-mark { position: absolute; top: -2px; transform: translateX(-50%); width: 20px; height: 20px; border-radius: 50%; display: grid; place-items: center; padding: 0;
  background: var(--panel, #fff); border: 1.5px solid var(--hue); color: var(--hue); cursor: pointer; z-index: 2; }
.sg-mark svg { width: 11px; height: 11px; }
.sg-mark:hover { background: var(--hue); color: #fff; }
.sg-overlay { position: absolute; top: 0; bottom: 0; left: var(--sg-label); right: 0; pointer-events: none; z-index: 3; }
.sg-today, .sg-cursor { position: absolute; top: 0; bottom: 0; width: 0; border-left: 2px solid #d4557a; }
.sg-cursor { border-left: 1px dashed var(--ink-3); }
.sg-today span, .sg-cursor span { position: absolute; top: 2px; left: 6px; font-size: 11px; font-weight: 700; white-space: nowrap; padding: 2px 7px; border-radius: 999px; }
.sg-today span { background: #d4557a; color: #fff; }
.sg-cursor span { background: var(--ink); color: var(--panel, #fff); top: auto; bottom: 4px; }
.sg-cursor.flip span { left: auto; right: 6px; }
.sg-empty { color: var(--ink-3); font-size: 13px; }
@media (max-width: 760px) { .sg { --sg-label: 160px; } .sg-hint { display: none; } }
</style>
