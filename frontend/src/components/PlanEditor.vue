<script setup>
import { computed, onMounted, provide, reactive, ref } from 'vue'
import { api } from '../api.js'
import { formatDate, countLabel } from '../lib/format.js'
import { OBSERVABILITY } from '../lib/labels.js'
import { bar, makeScale } from '../lib/gantt.js'
import Icon from './Icon.vue'
import PlanNode from './PlanNode.vue'

const props = defineProps({ buildingId: { type: Number, required: true } })
const emit = defineEmits(['changed'])

const plan = ref(null)
const error = ref('')
const busy = ref(false)
const query = ref('')
const open = reactive({})

const byParent = computed(() => {
  const map = {}
  for (const t of plan.value?.tasks || []) (map[t.parent_code || ''] ||= []).push(t)
  return map
})
const roots = computed(() => byParent.value[''] || [])
const needle = computed(() => query.value.trim().toLowerCase())
const scale = computed(() => plan.value && makeScale(plan.value.start_date, plan.value.end_date, 1000))

function phaseBar(p) {
  const b = bar(scale.value, p.start, p.end)
  return { left: b.x / 10 + '%', width: b.w / 10 + '%' }
}

function matches(task) {
  if (!needle.value) return true
  const self = task.name.toLowerCase().includes(needle.value) || task.code.startsWith(needle.value)
  return self || (byParent.value[task.code] || []).some(matches)
}

function applyDelta(delta) {
  // сервер присылает только затронутые строки: обновляем их на месте, чтобы не перерисовывать 254 работы
  const byCode = new Map(delta.tasks.map((t) => [t.code, t]))
  plan.value.tasks = plan.value.tasks.map((t) => byCode.get(t.code) || t)
  plan.value.phases = delta.phases
  plan.value.active_tasks = delta.active_tasks
}

async function run(fn) {
  busy.value = true
  error.value = ''
  try {
    const result = await fn()
    if (result.partial) applyDelta(result)
    else plan.value = result
    emit('changed')
  } catch (e) {
    error.value = e.message
  } finally {
    busy.value = false
  }
}

provide('plan', {
  childrenOf: (code) => byParent.value[code] || [],
  isOpen: (code) => Boolean(needle.value) || Boolean(open[code]),
  flip: (code) => { open[code] = !open[code] },
  matches,
  busy,
  toggle: (task) => run(() => api.updateTask(props.buildingId, task.id, { enabled: !task.enabled })),
  setDates: (task, start, end) => run(() => api.updateTask(props.buildingId, task.id, { start_date: start, end_date: end })),
})

function reschedule() {
  run(() => api.reschedule(props.buildingId))
}
function regenerate() {
  if (window.confirm('Вернуть план к исходному по справочнику? Ваши правки дат и отключённые работы сбросятся.')) {
    run(() => api.regenerate(props.buildingId))
  }
}

onMounted(async () => {
  try {
    plan.value = await api.plan(props.buildingId)
    for (const r of plan.value.tasks.filter((t) => !t.parent_code)) open[r.code] = true
  } catch (e) {
    error.value = e.message
  }
})
</script>

<template>
  <section class="stack">
    <div class="panel-scroll">
      <div class="panel-head">
        <div>
          <h2>Редактирование плана работ</h2>
          <!-- <p class="muted small">Сформирован по справочнику для типа объекта. Отключите работы, которых на объекте не будет, и поправьте сроки.</p> -->
        </div>
        <div class="row">
          <button class="btn ghost" type="button" :disabled="busy" @click="regenerate">Сбросить</button>
          <button class="btn" type="button" :disabled="busy" @click="reschedule"><Icon name="refresh" />Пересчитать сроки</button>
        </div>
      </div>
      <p v-if="error" class="error" role="alert">{{ error }}</p>

      <div v-if="plan" class="phases" role="table" aria-label="Этапы плана">
        <div v-for="p in plan.phases" :key="p.phase" class="phase" role="row">
          <div class="phase-name" role="cell">
            <b>{{ p.name }}</b>
            <span class="faint small">{{ countLabel(p.tasks, 'работа', 'работы', 'работ') }}, {{ formatDate(p.start) }} — {{ formatDate(p.end) }}</span>
          </div>
          <div class="phase-track" role="cell">
            <span class="phase-bar" :class="p.observability" :style="phaseBar(p)" :title="OBSERVABILITY[p.observability]"></span>
          </div>
          <div class="phase-obs small" :class="p.observability" role="cell">{{ OBSERVABILITY[p.observability] }}</div>
        </div>
      </div>
    </div>

    <div v-if="plan" class="panel">
      <div class="panel-head">
        <div>
          <h3>Все работы</h3>
          <p class="faint small">Активно {{ countLabel(plan.active_tasks, 'работа', 'работы', 'работ') }}</p>
        </div>
        <label class="search"><span class="sr">Поиск по плану</span>
          <input v-model="query" type="search" placeholder="Найти работу или номер пункта" /></label>
      </div>
      <ul class="tree" role="tree">
        <template v-for="t in roots" :key="t.id">
          <PlanNode v-if="matches(t)" :task="t" :depth="0" />
        </template>
      </ul>
    </div>
  </section>
</template>

<style scoped>
.phases { border-top: 1px solid var(--hair); }
.phase { display: grid; grid-template-columns: minmax(240px, 320px) minmax(0, 1fr) 180px; gap: 24px; align-items: center; padding: 13px 0; border-bottom: 1px solid var(--hair); }
.phase:last-child { border-bottom: 0; }
.phase-name { display: grid; gap: 2px; }
.phase-name b { font-weight: 500; font-size: 14px; }
.phase-track { position: relative; height: 6px; background: rgba(236, 235, 230, 0.06); border-radius: 3px; }
.phase-bar { position: absolute; top: 0; bottom: 0; border-radius: 3px; background: var(--accent); }
.phase-bar.medium { background: rgba(205, 183, 143, 0.6); }
.phase-bar.low, .phase-bar.none { background: repeating-linear-gradient(-45deg, rgba(236, 235, 230, 0.35) 0 3px, rgba(236, 235, 230, 0.1) 3px 6px); }
.phase-obs { color: var(--ink-3); }
.phase-obs.high { color: var(--ink-2); }
.search input { width: 320px; }
.tree { list-style: none; padding: 0; margin: 0; border-top: 1px solid var(--hair); }
@media (max-width: 900px) {
  .phase { grid-template-columns: 1fr; gap: 8px; }
  .search input { width: 100%; }
}
</style>
