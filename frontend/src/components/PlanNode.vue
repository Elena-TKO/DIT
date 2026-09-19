<script setup>
import { computed, inject, ref, watch } from 'vue'

const props = defineProps({
  task: { type: Object, required: true },
  depth: { type: Number, default: 0 },
})
const plan = inject('plan')

const children = computed(() => plan.childrenOf(props.task.code))
const expanded = computed(() => plan.isOpen(props.task.code))
const start = ref(props.task.start_date || '')
const end = ref(props.task.end_date || '')

watch(() => [props.task.start_date, props.task.end_date], ([s, e]) => {
  start.value = s || ''
  end.value = e || ''
})

function commitDates() {
  if (!start.value || !end.value) return
  if (start.value === props.task.start_date && end.value === props.task.end_date) return
  plan.setDates(props.task, start.value, end.value)
}
</script>

<template>
  <li role="treeitem" :aria-expanded="children.length ? expanded : undefined">
    <div class="node" :class="{ off: !task.active, summary: task.is_summary }" :style="{ paddingLeft: 8 + depth * 22 + 'px' }">
      <button v-if="children.length" class="twisty" type="button" :aria-label="expanded ? 'Свернуть' : 'Развернуть'"
        @click="plan.flip(task.code)">{{ expanded ? '−' : '+' }}</button>
      <span v-else class="twisty-space"></span>
      <input type="checkbox" :checked="task.enabled" :disabled="plan.busy.value" :aria-label="`Включить: ${task.name}`"
        @change="plan.toggle(task)" />
      <span class="code">{{ task.code.includes('.u') ? '' : task.code }}</span>
      <span class="name">{{ task.name }}</span>
      <span v-if="task.phase_name" class="phase">{{ task.phase_name }}</span>
      <span v-if="task.is_summary" class="dates muted small">
        <template v-if="task.start_date">{{ task.start_date }} — {{ task.end_date }}</template>
      </span>
      <span v-else class="dates">
        <input v-model="start" type="date" :disabled="!task.active || plan.busy.value" aria-label="Начало" @change="commitDates" />
        <input v-model="end" type="date" :disabled="!task.active || plan.busy.value" aria-label="Окончание" @change="commitDates" />
      </span>
    </div>
    <ul v-if="children.length && expanded" role="group">
      <template v-for="c in children" :key="c.id">
        <PlanNode v-if="plan.matches(c)" :task="c" :depth="depth + 1" />
      </template>
    </ul>
  </li>
</template>

<style scoped>
ul { list-style: none; padding: 0; margin: 0; }
.node { display: grid; grid-template-columns: 26px 17px 64px minmax(0, 1fr) auto auto; gap: 14px; align-items: center; padding: 9px 6px; border-bottom: 1px solid var(--hair); font-size: 13.5px; }
.node:hover { background: rgba(236, 235, 230, 0.025); }
.node.summary .name { font-weight: 500; color: var(--ink); }
.name { color: var(--ink-2); }
.node.off .name { color: var(--ink-3); text-decoration: line-through; text-decoration-color: rgba(236, 235, 230, 0.2); }
.twisty { width: 26px; height: 26px; border: 1px solid var(--hair-2); background: transparent; border-radius: 50%; cursor: pointer; line-height: 1; font: inherit; color: var(--ink-2); }
.twisty:hover { border-color: var(--accent); color: var(--accent); }
.code { font-size: 12px; color: var(--ink-3); }
.phase { font-size: 12px; color: var(--ink-3); border: 1px solid var(--hair); padding: 2px 9px; border-radius: 7px; white-space: nowrap; }
.dates { display: flex; gap: 6px; }
.dates input { padding: 5px 8px; font-size: 12.5px; border-color: var(--hair); }
@media (max-width: 900px) {
  .node { grid-template-columns: 26px 17px minmax(0, 1fr); }
  .code, .phase { display: none; }
  .dates { grid-column: 3; }
}
</style>
