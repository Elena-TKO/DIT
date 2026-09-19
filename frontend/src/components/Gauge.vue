<script setup>
import { computed } from 'vue'

const props = defineProps({
  value: { type: Number, default: null },
  plan: { type: Number, default: null },
  size: { type: Number, default: 132 },
})

const R = 54
const C = 2 * Math.PI * R
const clamp = (v) => Math.max(0, Math.min(100, v || 0))
const known = computed(() => props.value !== null && props.value !== undefined)
const dash = computed(() => `${(known.value ? clamp(props.value) : 0) / 100 * C} ${C}`)
const planAngle = computed(() => (clamp(props.plan) / 100) * 360 - 90)
</script>

<template>
  <div class="gauge" :style="{ width: size + 'px', height: size + 'px' }" role="img"
    :aria-label="known ? `Готовность ${value}%, по графику ${plan}%` : 'Готовность неизвестна: снимков ещё нет'">
    <svg viewBox="0 0 120 120">
      <circle cx="60" cy="60" :r="R" class="track" />
      <circle cx="60" cy="60" :r="R" class="value" :stroke-dasharray="dash" transform="rotate(-90 60 60)" />
      <line v-if="plan !== null" x1="60" y1="1" x2="60" y2="13" class="plan" :transform="`rotate(${planAngle + 90} 60 60)`" />
    </svg>
    <div class="gauge-text">
      <span class="gauge-num" :class="{ unknown: !known }">{{ known ? Math.round(value) : '—' }}<small v-if="known">%</small></span>
      <span class="gauge-label">{{ known ? 'готовность' : 'нет снимков' }}</span>
    </div>
  </div>
</template>

<style scoped>
.gauge { position: relative; flex: none; }
svg { width: 100%; height: 100%; display: block; }
circle { fill: none; stroke-width: 2.5; }
.track { stroke: rgba(236, 235, 230, 0.16); }
.value { stroke: var(--accent); stroke-linecap: round; transition: stroke-dasharray 1.4s var(--ease); }
.plan { stroke: var(--ink); stroke-width: 2; stroke-linecap: round; }
.gauge-text { position: absolute; inset: 0; display: grid; place-content: center; text-align: center; }
.gauge-num.unknown { color: var(--ink-3); }
.gauge-num { font-family: var(--serif); font-size: 44px; line-height: 1; font-variant-numeric: lining-nums; }
.gauge-num small { font-size: 20px; margin-left: 1px; }
.gauge-label { font-size: 11.5px; color: rgba(236, 235, 230, 0.66); margin-top: 4px; }
</style>
