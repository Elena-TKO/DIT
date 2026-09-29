<script setup>
import { computed, onMounted, ref } from 'vue'
import { api } from '../api.js'
import Icon from './Icon.vue'
import StagesOverview from './StagesOverview.vue'

// План работ: Гант «план ↔ факт по снимкам», таблица «Все работы» по этапам и техника за окно анализа.
const props = defineProps({ building: { type: Object, required: true } })
const emit = defineEmits(['changed'])
const analysis = ref(null)
const error = ref('')
const busy = ref(false)
const overview = ref(null)
const equipment = computed(() => analysis.value?.verdict?.observed ? analysis.value.verdict.equipment || [] : [])

async function loadAnalysis() {
  analysis.value = await api.analysis(props.building.id).catch(() => null)
}

async function update(reset = false) {
  if (reset && !window.confirm('Сбросить изменения календарного плана к исходному справочнику?')) return
  busy.value = true
  error.value = ''
  try {
    if (reset) await api.regenerate(props.building.id)
    else await api.reschedule(props.building.id)
    await Promise.all([overview.value?.load(), loadAnalysis()])
  } catch (e) {
    error.value = e.message
  } finally {
    busy.value = false
  }
}

function changed() {
  loadAnalysis()
  emit('changed')
}

onMounted(loadAnalysis)
</script>

<template>
  <section class="work-plan">
    <header class="review-heading">
      <div><h1>План работ</h1><p>{{ building.name }} · план этапов, факт по снимкам и нужная техника</p></div>
      <div class="review-actions">
        <button class="btn" type="button" :disabled="busy" @click="update(true)">Сбросить</button>
        <button class="btn primary" type="button" :disabled="busy" @click="update(false)"><Icon name="refresh" />Пересчитать</button>
      </div>
    </header>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <StagesOverview ref="overview" :building="building" @changed="changed" />
    <section class="review-panel equipment-matrix">
      <h2>Техника на площадке</h2>
      <p class="review-caption">Сводка за окно анализа {{ analysis?.verdict?.window_hours || 24 }} ч по последним снимкам.</p>
      <div class="table-scroll">
        <table class="light-table matrix-table">
          <thead><tr><th>Техника</th><th>Работает</th><th>Простаивает</th><th>Снимков</th><th>Зоны</th></tr></thead>
          <tbody>
            <tr v-for="e in equipment" :key="e.cls">
              <th>{{ e.label || e.cls }}</th>
              <td><span class="matrix-cell working">{{ e.working ?? '—' }}</span></td>
              <td><span class="matrix-cell" :class="e.idle ? 'idle' : 'unknown'">{{ e.idle ?? '—' }}</span></td>
              <td>{{ e.photos ?? '—' }}</td>
              <td>{{ (e.zones || []).join(', ') || '—' }}</td>
            </tr>
            <tr v-if="!equipment.length"><td colspan="5" class="table-empty">Нет наблюдений техники. <RouterLink :to="`/buildings/${building.id}/photos`">Загрузить фото →</RouterLink></td></tr>
          </tbody>
        </table>
      </div>
      <p class="review-caption">Один снимок не позволяет измерить длительность простоя — нужна серия кадров одной камеры.</p>
    </section>
  </section>
</template>

<style>
.work-plan > .so { margin-bottom: 24px; }
</style>
