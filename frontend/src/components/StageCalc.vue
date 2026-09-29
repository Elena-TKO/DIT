<script setup>
import { computed, ref, watch } from 'vue'
import { api } from '../api.js'

// Расчёт количества техники для этапа по формулам METHODOLOGY.md (сервер: POST /api/methodology/calc).
const props = defineProps({ kind: { type: String, required: true } })

const FIELDS = {
  excavation: [
    { key: 'volume_m3', label: 'Объём грунта, м³', value: 20000 },
    { key: 'days', label: 'Срок, сут', value: 20 },
    { key: 'shifts', label: 'Смен в сутки', value: 1 },
    { key: 'bucket_m3', label: 'Ковш экскаватора, м³', value: 1 },
    { key: 'truck_t', label: 'Самосвал, т', value: 20 },
    { key: 'distance_km', label: 'Плечо вывоза, км', value: 10 },
  ],
  concreting: [
    { key: 'volume_m3', label: 'Объём бетона, м³', value: 480 },
    { key: 'hours', label: 'Время укладки, ч', value: 16 },
    { key: 'pump_m3h', label: 'Бетононасос, м³/ч', value: 30 },
    { key: 'mixer_m3', label: 'Миксер, м³', value: 7 },
    { key: 'distance_km', label: 'До бетонного узла, км', value: 10 },
  ],
  tower_crane: [
    { key: 'building_height_m', label: 'Высота здания, м', value: 75 },
    { key: 'building_width_m', label: 'Ширина здания, м', value: 18 },
    { key: 'building_length_m', label: 'Длина здания, м', value: 120 },
    { key: 'element_t', label: 'Самый тяжёлый элемент, т', value: 3 },
  ],
}
const TITLES = { excavation: 'Земляные работы', concreting: 'Бетонирование', tower_crane: 'Башенный кран' }

const params = ref({})
const result = ref(null)
const error = ref('')
const busy = ref(false)
const fields = computed(() => FIELDS[props.kind] || [])
const UNITS = { excavator: 'экскаваторов', dump_truck: 'самосвалов', concrete_pump: 'бетононасосов',
  concrete_mixer: 'автобетоносмесителей', tower_crane: 'башенных кранов', hook_height_m: 'м — высота крюка',
  reach_m: 'м — требуемый вылет', load_t: 'т — грузоподъёмность' }

watch(() => props.kind, () => {
  params.value = Object.fromEntries(fields.value.map((f) => [f.key, f.value]))
  result.value = null
}, { immediate: true })

async function run() {
  busy.value = true
  error.value = ''
  try {
    result.value = await api.methodologyCalc(props.kind, params.value)
  } catch (e) {
    error.value = e.message
    result.value = null
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <form class="sc" @submit.prevent="run">
    <div class="sc-head">
      <b>Расчёт техники: {{ TITLES[kind] }}</b>
      <span>по формулам методики (МДС 12-81.2007, СП 45/70.13330) — точнее, чем типовой диапазон</span>
    </div>
    <div class="sc-fields">
      <label v-for="f in fields" :key="f.key" class="sc-field">{{ f.label }}
        <input v-model.number="params[f.key]" type="number" min="0" step="any" required />
      </label>
      <button class="btn primary" type="submit" :disabled="busy">{{ busy ? 'Считаем…' : 'Рассчитать' }}</button>
    </div>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <div v-if="result" class="sc-result">
      <div class="sc-answer">
        <span v-for="(v, k) in result.result" :key="k"><b>{{ v }}</b> {{ UNITS[k] || k }}</span>
      </div>
      <table class="sc-steps">
        <tbody>
          <tr v-for="s in result.steps" :key="s.name"><td>{{ s.name }}</td><td class="sc-formula">{{ s.formula }}</td><td class="sc-value">{{ s.value }} {{ s.unit }}</td></tr>
        </tbody>
      </table>
      <p v-for="w in result.warnings || []" :key="w" class="sc-warn">{{ w }}</p>
      <p class="sc-docs">Нормативы: {{ result.docs.join('; ') }}</p>
    </div>
  </form>
</template>

<style>
.sc { display: grid; gap: 14px; }
.sc-head { display: grid; gap: 2px; }
.sc-head b { font-size: 15px; }
.sc-head span { font-size: 12px; color: var(--ink-3); }
.sc-fields { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 12px; align-items: end; }
.sc-field { display: grid; gap: 4px; font-size: 11px; color: var(--ink-3); }
.sc-field input { font: inherit; font-size: 13px; padding: 7px 9px; }
.sc-answer { display: flex; flex-wrap: wrap; gap: 10px 22px; font-size: 13px; }
.sc-answer b { font-family: var(--serif); font-size: 28px; font-weight: 500; color: var(--accent); margin-right: 4px; }
.sc-steps { width: 100%; border-collapse: collapse; font-size: 12px; }
.sc-steps td { padding: 6px 8px; border-top: 1px solid var(--hair); }
.sc-formula { font-family: ui-monospace, "SFMono-Regular", Consolas, monospace; color: var(--ink-3); white-space: nowrap; }
.sc-value { text-align: right; white-space: nowrap; font-weight: 600; }
.sc-warn { margin: 0; color: var(--warning); font-size: 12px; }
.sc-docs { margin: 0; color: var(--ink-3); font-size: 11px; }
</style>
