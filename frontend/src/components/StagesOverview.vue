<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api.js'
import { countLabel } from '../lib/format.js'
import StageGantt from './StageGantt.vue'
import StagesTable from './StagesTable.vue'

// План ↔ факт по этапам: Гант и таблица «Все работы». Данные — /buildings/{id}/stages,
// где факт этапа считается по снимкам, этап которых определён автоматически или выбран при загрузке.
const props = defineProps({
  building: { type: Object, required: true },
  showTable: { type: Boolean, default: true },
})
const emit = defineEmits(['changed'])

const data = ref(null)
const error = ref('')
const loading = ref(false)

async function load() {
  loading.value = true
  error.value = ''
  try {
    data.value = await api.stages(props.building.id)
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

function onUploaded() {
  load()
  emit('changed')
}

onMounted(load)
defineExpose({ load })
</script>

<template>
  <div class="so">
    <p v-if="error" class="error" role="alert">{{ error }} <button class="btn small" type="button" @click="load">Повторить</button></p>
    <p v-else-if="loading && !data" class="so-muted" role="status">Загружаем этапы…</p>
    <template v-if="data">
      <section class="review-panel so-panel">
        <div class="so-head">
          <h2>Этапы: план и факт</h2>
          <span class="so-muted">
            Факт — по датам проанализированных снимков этапа<template v-if="data.unassigned_photos">
            · {{ countLabel(data.unassigned_photos, 'снимок', 'снимка', 'снимков') }} без этапа (техника не найдена)</template>
          </span>
        </div>
        <StageGantt :stages="data.stages" :start="data.start" :end="data.end" :today="data.today" :building-id="building.id" />
      </section>
      <section v-if="showTable" class="review-panel so-panel">
        <div class="so-head"><h2>Все работы</h2></div>
        <StagesTable :stages="data.stages" :building-id="building.id" @uploaded="onUploaded" />
      </section>
    </template>
  </div>
</template>

<style>
.so { display: grid; gap: 24px; }
.so-panel { overflow: visible; }
.so-head { display: flex; justify-content: space-between; align-items: baseline; gap: 16px; flex-wrap: wrap; margin-bottom: 16px; }
.so-muted { color: var(--ink-3); font-size: 12px; }
.design-classic .so-panel { background: var(--panel); border: 1px solid var(--hair); border-radius: var(--r-l); padding: 26px 28px; }
.design-classic .so-head h2 { font-size: 28px; }
</style>
