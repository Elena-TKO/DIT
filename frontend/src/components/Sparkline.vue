<script setup>
import { computed } from 'vue'
import { formatDate } from '../lib/format.js'

const props = defineProps({
  points: { type: Array, default: () => [] },   // [{ at, completion_percent, planned_percent }]
})

const W = 1000
const H = 150
const PAD = 14

const series = computed(() => props.points.filter((p) => p.completion_percent !== null))
const max = computed(() => Math.max(10, ...series.value.map((p) => Math.max(p.completion_percent || 0, p.planned_percent || 0))) * 1.15)
const x = (i) => (series.value.length < 2 ? 0 : (i / (series.value.length - 1)) * (W - PAD * 2) + PAD)
const y = (v) => H - PAD - ((v || 0) / max.value) * (H - PAD * 2)

function line(key) {
  return series.value.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)} ${y(p[key]).toFixed(1)}`).join(' ')
}
const area = computed(() => {
  if (series.value.length < 2) return ''
  return `${line('completion_percent')} L${x(series.value.length - 1).toFixed(1)} ${H - PAD} L${x(0).toFixed(1)} ${H - PAD} Z`
})
const last = computed(() => series.value[series.value.length - 1])
const first = computed(() => series.value[0])
const ticks = computed(() => [0, max.value / 2, max.value].map((v) => ({ v: Math.round(v), y: y(v) })))
</script>

<template>
  <div v-if="series.length >= 2" class="chart">
    <svg :viewBox="`0 0 ${W} ${H}`" preserveAspectRatio="none" class="spark" role="img"
      :aria-label="`Готовность выросла с ${first.completion_percent}% до ${last.completion_percent}%`">
      <line v-for="t in ticks" :key="t.v" :x1="PAD" :x2="W - PAD" :y1="t.y" :y2="t.y" class="grid" />
      <path :d="area" class="area" />
      <path :d="line('planned_percent')" class="plan" />
      <path :d="line('completion_percent')" class="fact" />
      <circle v-for="(p, i) in series" :key="i" :cx="x(i)" :cy="y(p.completion_percent)" r="3" class="dot" />
    </svg>
    <div class="scale" aria-hidden="true">
      <span v-for="t in ticks" :key="t.v" :style="{ top: (t.y / H) * 100 + '%' }">{{ t.v }}%</span>
    </div>
    <div class="axis small faint">
      <span>{{ formatDate(first.at) }} — {{ first.completion_percent }}%</span>
      <span>{{ formatDate(last.at) }} — {{ last.completion_percent }}%</span>
    </div>
  </div>
  <p v-else class="faint small empty-hint">
    Динамика появится, когда в журнал попадут хотя бы две записи: нажмите «Записать в журнал» на этом шаге.
  </p>
</template>

<style scoped>
.chart { position: relative; padding-left: 40px; }
.spark { width: 100%; height: 150px; display: block; }
.grid { stroke: var(--hair); stroke-width: 1; vector-effect: non-scaling-stroke; }
path { fill: none; stroke-width: 2; vector-effect: non-scaling-stroke; }
.area { fill: rgba(205, 183, 143, 0.1); stroke: none; }
.plan { stroke: var(--ink-3); stroke-dasharray: 5 5; stroke-width: 1.5; }
.fact { stroke: var(--accent); }
.dot { fill: var(--night); stroke: var(--accent); stroke-width: 2; vector-effect: non-scaling-stroke; }
.scale { position: absolute; left: 0; top: 0; bottom: 0; width: 36px; }
.scale span { position: absolute; right: 0; transform: translateY(-50%); font-size: 11px; color: var(--ink-3); }
.axis { display: flex; justify-content: space-between; margin-top: 8px; }
.empty-hint { margin: 0; }
</style>
