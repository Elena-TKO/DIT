<script setup>
import { computed, onMounted, ref } from 'vue'
import { api } from '../api.js'
import { formatDate } from '../lib/format.js'
import { bar, makeScale, monthTicks } from '../lib/gantt.js'
import Icon from './Icon.vue'
const props = defineProps({ building: { type: Object, required: true } })
const plan = ref(null)
const analysis = ref(null)
const timeline = ref(null)
const error = ref('')
const partialError = ref('')
const busy = ref(false)
const query = ref('')
const scale = computed(() => plan.value ? makeScale(plan.value.start_date,plan.value.end_date,1000) : null)
const ticks = computed(() => plan.value ? monthTicks(plan.value.start_date,plan.value.end_date,1000,65) : [])
const tasks = computed(() => (plan.value?.tasks || []).filter(t => t.active !== false && (t.name+' '+t.code).toLowerCase().includes(query.value.trim().toLowerCase())))
const equipment = computed(() => analysis.value?.verdict?.observed ? analysis.value.verdict.equipment || [] : [])
const delayByCode = computed(() => Object.fromEntries((timeline.value?.rows || []).flatMap(r => r.tasks || []).map(t => [t.code,t.delay_days])))
function position(phase) { const value = bar(scale.value,phase.start,phase.end); return {left:value.x/10+'%',width:value.w/10+'%'} }
function description(task) {
  const check = (analysis.value?.verdict?.checklist || []).find(c => (c.tasks || []).some(t => t.code === task.code || t.id === task.id))
  return check ? (check.required || []).map(g => (g.labels || []).join(' или ')).join(', ') || check.hint || '—' : '—'
}
async function load() {
  busy.value=true; error.value=''; partialError.value=''
  try {
    plan.value=await api.plan(props.building.id)
    const results=await Promise.allSettled([api.analysis(props.building.id),api.timeline(props.building.id)])
    analysis.value=results[0].status==='fulfilled'?results[0].value:null
    timeline.value=results[1].status==='fulfilled'?results[1].value:null
    if(results.some(r=>r.status==='rejected')) partialError.value='План загружен. Часть результатов анализа недоступна.'
  }catch(e){error.value=e.message}finally{busy.value=false}
}
async function update(reset=false) {
  if(reset && !window.confirm('Сбросить изменения календарного плана к исходному справочнику?')) return
  busy.value=true;error.value=''
  try { if(reset) await api.regenerate(props.building.id); else await api.reschedule(props.building.id); await load() }
  catch(e){error.value=e.message}finally{busy.value=false}
}
onMounted(load)
</script>
<template>
  <section class="work-plan">
    <header class="review-heading"><div><h1>План работ</h1><p>{{ building.name }} · календарный план и правила «этап → техника»</p></div><div class="review-actions"><button class="btn" :disabled="busy || !plan" @click="update(true)">Сбросить</button><button class="btn primary" :disabled="busy || !plan" @click="update(false)"><Icon name="refresh" />Пересчитать</button></div></header>
    <p v-if="error" class="error" role="alert">{{ error }} <button class="btn small" @click="load">Повторить</button></p><p v-if="partialError" class="review-notice">{{ partialError }}</p><p v-if="busy" role="status">Загружаем план…</p>
    <template v-if="plan">
      <section class="review-panel phase-panel"><h2>Этапы</h2><div class="table-scroll"><div class="phase-chart"><div class="phase-row phase-months"><span></span><div class="phase-track"><span v-for="(tick,i) in ticks" :key="i" class="phase-tick" :style="{left:tick.x/10+'%'}">{{ tick.label }}</span></div></div><div v-for="(p,i) in plan.phases || []" :key="p.phase || i" class="phase-row"><span>{{ p.name }}</span><div class="phase-track"><i v-for="(tick,j) in ticks" :key="j" class="phase-gridline" :style="{left:tick.x/10+'%'}"></i><span class="phase-strip" :class="'phase-color-'+i%3" :style="position(p)" :title="formatDate(p.start)+' — '+formatDate(p.end)"></span></div></div><p v-if="!plan.phases?.length">Этапы ещё не сформированы.</p></div></div></section>
      <section class="review-panel equipment-matrix"><h2>Техника по времени</h2><p class="review-caption">Сводка за окно анализа {{ analysis?.verdict?.window_hours || 24 }} ч. Разбивка по 30 минутам пока недоступна.</p><div class="table-scroll"><table class="light-table matrix-table"><thead><tr><th>Техника</th><th>Работает</th><th>Простаивает</th><th>Снимков</th><th>Зоны</th></tr></thead><tbody><tr v-for="e in equipment" :key="e.cls"><th>{{ e.label || e.cls }}</th><td><span class="matrix-cell working">{{ e.working ?? '—' }}</span></td><td><span class="matrix-cell" :class="e.idle ? 'idle' : 'unknown'">{{ e.idle ?? '—' }}</span></td><td>{{ e.photos ?? '—' }}</td><td>{{ (e.zones || []).join(', ') || '—' }}</td></tr><tr v-if="!equipment.length"><td colspan="5" class="table-empty">Нет наблюдений техники. <RouterLink :to="`/buildings/${building.id}/photos`">Загрузить фото →</RouterLink></td></tr></tbody></table></div><p class="review-caption">Один снимок не позволяет измерить длительность простоя.</p></section>
      <section class="review-panel work-table-panel"><div class="section-heading"><div><h2>Все работы</h2><p class="review-caption">Активно {{ plan.active_tasks ?? tasks.length }} работ</p></div><label class="work-search"><span class="sr">Найти работу или номер пункта</span><input v-model="query" placeholder="Найти работу или номер пункта" type="search" /></label></div><div class="table-scroll"><table class="light-table work-table"><thead><tr><th>Работа</th><th>Сроки</th><th>Описание техники</th><th>Фото</th><th>Задержка</th><th>Приоритет</th></tr></thead><tbody><tr v-for="t in tasks" :key="t.id || t.code" :class="{ 'summary-row':t.is_summary }"><th>{{ t.code }} {{ t.name }}</th><td>{{ formatDate(t.start_date) }} — {{ formatDate(t.end_date) }}</td><td>{{ description(t) }}</td><td><RouterLink :to="`/buildings/${building.id}/photos`" class="table-upload" title="Загрузка фото объекта. Привязка к отдельной работе пока не поддерживается."><Icon name="upload" />Загрузить</RouterLink></td><td :class="{ 'delay-value':delayByCode[t.code]>0 }">{{ timeline?.observed && delayByCode[t.code] != null ? delayByCode[t.code] + ' дн.' : '—' }}</td><td title="Приоритет отдельной работы пока не передаётся">—</td></tr><tr v-if="!tasks.length"><td colspan="6" class="table-empty">{{ query ? 'Работы не найдены. Попробуйте другое название.' : 'В плане пока нет активных работ.' }}</td></tr></tbody></table></div></section>
      <p class="review-caption plan-note">Фото загружается на объект целиком. Задержки показываются только при наличии результатов анализа; приоритеты работ пока не определяются.</p>
    </template>
  </section>
</template>
