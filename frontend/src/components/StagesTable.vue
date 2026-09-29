<script setup>
import { computed, reactive, ref } from 'vue'
import { formatDate } from '../lib/format.js'
import Icon from './Icon.vue'
import PhotoCell from './PhotoCell.vue'

// «Все работы»: одна строка — один главный этап. Подпункты (работы справочника) — в раскрывающемся
// списке внутри строки, с уточнением нужной техники (без загрузки фото на отдельную работу).
const props = defineProps({
  stages: { type: Array, default: () => [] },
  buildingId: { type: Number, required: true },
})
const emit = defineEmits(['uploaded'])

const open = reactive({})
const query = ref('')
const q = computed(() => query.value.trim().toLowerCase())
const visible = computed(() => props.stages
  .map((s) => ({ ...s, shownTasks: q.value ? s.tasks.filter((t) => `${t.code} ${t.name}`.toLowerCase().includes(q.value)) : s.tasks }))
  .filter((s) => !q.value || s.name.toLowerCase().includes(q.value) || s.shownTasks.length))

function isOpen(s) {
  return open[s.phase] ?? (Boolean(q.value) && s.shownTasks.length > 0)
}
function toggle(s) {
  open[s.phase] = !isOpen(s)
}
function range(r) {
  if (!r) return ''
  return r.max_count === null || r.max_count === undefined ? `от ${r.min_count}` : r.min_count === r.max_count ? `${r.min_count}` : `${r.min_count}–${r.max_count}`
}
const required = (s) => s.equipment.filter((e) => e.role === 'required')
const typical = (s) => s.equipment.filter((e) => e.role === 'typical')
</script>

<template>
  <div class="st">
    <div class="st-top">
      <p class="st-caption">{{ stages.length }} этапов · подпункты работ раскрываются по клику на этап</p>
      <label class="st-search"><span class="sr">Найти этап или работу</span>
        <input v-model="query" type="search" placeholder="Найти этап, работу или номер пункта" /></label>
    </div>
    <div class="st-scroll">
      <table class="st-table">
        <thead>
          <tr><th>Этап работ</th><th>План</th><th>Факт по снимкам</th><th>Нужная техника</th><th>Фото</th><th>Задержка</th></tr>
        </thead>
        <tbody>
          <template v-for="s in visible" :key="s.phase">
            <tr class="st-stage" :class="{ open: isOpen(s) }">
              <th>
                <button type="button" class="st-toggle" :aria-expanded="isOpen(s)" @click="toggle(s)">
                  <span class="st-chev" aria-hidden="true">›</span>
                  <span><b>{{ s.name }}</b><small>{{ s.tasks.length }} работ<template v-if="s.status_label"> · <i class="st-dot" :style="{ background: s.color }"></i>{{ s.status_label }}</template><template v-if="s.observability === 'none'"> · вне камер</template></small></span>
                </button>
              </th>
              <td class="st-dates">{{ formatDate(s.start) }}<br />{{ formatDate(s.end) }}</td>
              <td class="st-dates">
                <template v-if="s.photo_start">{{ formatDate(s.photo_start) }}<br />{{ formatDate(s.photo_end) }}</template>
                <span v-else class="st-muted">нет снимков</span>
              </td>
              <td>
                <span v-for="e in required(s)" :key="e.cls" class="st-eq req" :title="`Обязательная${e.group !== null ? ', группа ' + (e.group + 1) : ''}. Норма на захватку: ${range(e)}`">{{ e.label }} <em>{{ range(e) }}</em></span>
                <span v-for="e in typical(s)" :key="e.cls" class="st-eq" :title="`Типичная. Норма: ${range(e)}`">{{ e.label }}</span>
                <span v-if="!s.equipment.length" class="st-muted">не требуется</span>
              </td>
              <td><PhotoCell :building-id="buildingId" :stage="s" @uploaded="emit('uploaded', $event)" /></td>
              <td :class="{ 'st-late': s.delay_days > 0 }">{{ s.delay_days > 0 ? s.delay_days + ' дн.' : '—' }}</td>
            </tr>
            <tr v-if="isOpen(s)" class="st-sub">
              <td colspan="6">
                <table class="st-subtable">
                  <thead><tr><th>№</th><th>Работа</th><th>Сроки</th><th>Используемая техника</th></tr></thead>
                  <tbody>
                    <tr v-for="t in s.shownTasks" :key="t.id">
                      <td class="st-code">{{ t.code }}</td>
                      <td>{{ t.name }}</td>
                      <td class="st-dates">{{ formatDate(t.start_date) }} — {{ formatDate(t.end_date) }}</td>
                      <td>{{ t.equipment.map((e) => e.label).join(', ') || '—' }}</td>
                    </tr>
                    <tr v-if="!s.shownTasks.length"><td colspan="4" class="st-muted">Работ нет.</td></tr>
                  </tbody>
                </table>
              </td>
            </tr>
          </template>
          <tr v-if="!visible.length"><td colspan="6" class="st-muted">{{ query ? 'Ничего не найдено.' : 'В плане пока нет этапов.' }}</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style>
.st-top { display: flex; justify-content: space-between; align-items: center; gap: 16px; flex-wrap: wrap; margin-bottom: 12px; }
.st-caption { margin: 0; font-size: 12px; color: var(--ink-3); }
.st-search input { width: 320px; max-width: 100%; }
.st-scroll { overflow-x: auto; }
.st-table { width: 100%; border-collapse: collapse; font-size: 13px; min-width: 860px; }
.st-table > thead th { text-align: left; font-size: 11px; font-weight: 700; color: var(--ink-3); text-transform: uppercase; padding: 8px 10px; border-bottom: 1px solid var(--hair-2); }
.st-stage > th, .st-stage > td { padding: 12px 10px; border-bottom: 1px solid var(--hair); vertical-align: middle; text-align: left; }
.st-stage.open > th, .st-stage.open > td { border-bottom-color: transparent; background: color-mix(in srgb, var(--accent) 5%, transparent); }
.st-toggle { display: flex; gap: 10px; align-items: flex-start; background: none; border: 0; padding: 0; font: inherit; color: inherit; text-align: left; cursor: pointer; }
.st-toggle b { display: block; font-size: 14px; font-weight: 600; }
.st-toggle small { display: flex; align-items: center; gap: 4px; flex-wrap: wrap; font-size: 11px; color: var(--ink-3); margin-top: 2px; }
.st-chev { display: inline-block; font-size: 18px; line-height: 18px; color: var(--ink-3); transition: transform 0.2s; }
.st-stage.open .st-chev { transform: rotate(90deg); color: var(--accent); }
.st-dot { display: inline-block; width: 7px; height: 7px; border-radius: 50%; }
.st-dates { white-space: nowrap; font-size: 12px; }
.st-muted { color: var(--ink-3); font-size: 12px; }
.st-eq { display: inline-block; margin: 2px 4px 2px 0; padding: 2px 8px; border-radius: 999px; font-size: 11px; border: 1px solid var(--hair-2); color: var(--ink-2, var(--ink)); }
.st-eq.req { border-color: color-mix(in srgb, var(--accent) 55%, transparent); color: var(--ink); }
.st-eq em { font-style: normal; color: var(--accent); font-weight: 700; margin-left: 2px; }
.st-late { color: var(--critical); font-weight: 600; }
.st-sub > td { padding: 0 10px 14px 38px; border-bottom: 1px solid var(--hair); background: color-mix(in srgb, var(--accent) 5%, transparent); }
.st-subtable { width: 100%; border-collapse: collapse; font-size: 12px; background: var(--panel, #fff); border-radius: 10px; overflow: hidden; }
.st-subtable th { text-align: left; font-size: 10px; text-transform: uppercase; color: var(--ink-3); padding: 7px 10px; border-bottom: 1px solid var(--hair); font-weight: 700; }
.st-subtable td { padding: 7px 10px; border-bottom: 1px solid var(--hair); vertical-align: top; }
.st-subtable tr:last-child td { border-bottom: 0; }
.st-code { color: var(--ink-3); white-space: nowrap; }
</style>
