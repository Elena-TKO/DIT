<script setup>
import { onMounted, ref } from 'vue'
import { api, deviationsCsvUrl, reportUrl } from '../api.js'
import { formatDateTime } from '../lib/format.js'
import Icon from './Icon.vue'

const props = defineProps({
  building: { type: Object, required: true },
})
const log = ref([])
const error = ref('')
const link = ref(null)
const linkTtl = ref(72)
const copied = ref(false)
const busy = ref(false)

async function makeLink() {
  busy.value = true
  error.value = ''
  try {
    const result = await api.reportLink(props.building.project_id, linkTtl.value)
    link.value = { ...result, url: window.location.origin + result.path }
    copied.value = false
  } catch (e) {
    error.value = e.message
  } finally {
    busy.value = false
  }
}

async function copyLink() {
  try {
    await navigator.clipboard.writeText(link.value.url)
    copied.value = true
  } catch {
    copied.value = false
  }
}

onMounted(async () => {
  try {
    log.value = await api.deviations(props.building.id)
  } catch (e) {
    error.value = e.message
  }
})
</script>

<template>
  <section class="stack">
    <div class="report-card">
      <span class="report-icon"><Icon name="report" /></span>
      <div>
        <h2>Отчёт по стройке</h2>
        <p>Готовность и статусы объектов, фактический этап, отклонения со снимками, рекомендации и советы по размещению камер. Сохраняется в PDF через печать браузера.</p>
      </div>
      <a class="btn primary" :href="reportUrl(building.project_id)" target="_blank" rel="noopener">Открыть отчёт</a>
    </div>

    <div class="panel">
      <div class="panel-head">
        <div>
          <h3>Ссылка для заказчика</h3>
          <p class="faint small">Открывает только этот отчёт и только на чтение: вход и доступ к снимкам не требуются.</p>
        </div>
        <div class="row">
          <label class="field inline small">Срок
            <select v-model.number="linkTtl">
              <option :value="24">сутки</option>
              <option :value="72">3 суток</option>
              <option :value="168">неделя</option>
              <option :value="720">30 суток</option>
            </select>
          </label>
          <button class="btn" type="button" :disabled="busy" @click="makeLink">Создать ссылку</button>
        </div>
      </div>
      <div v-if="link" class="link-row">
        <code>{{ link.url }}</code>
        <button class="btn small" type="button" @click="copyLink">{{ copied ? 'Скопировано' : 'Копировать' }}</button>
        <span class="faint small nowrap">действует до {{ formatDateTime(link.expires_at) }}</span>
      </div>
    </div>

    <div class="panel">
      <div class="panel-head">
        <div>
          <h3>Журнал отклонений</h3>
          <p class="faint small">Вердикты, записанные на шаге «Этап и отклонения».</p>
        </div>
        <a v-if="log.length" class="btn small" :href="deviationsCsvUrl(building.id)" download>Выгрузить CSV</a>
      </div>
      <p v-if="error" class="error">{{ error }}</p>
      <div v-if="!log.length" class="empty small"><p>Журнал пуст. Запишите вердикт на шаге «Этап и отклонения».</p></div>
      <table v-else class="data">
        <thead><tr><th>Момент</th><th>Важность</th><th>Этап</th><th>Отклонение</th></tr></thead>
        <tbody>
          <tr v-for="d in log" :key="d.id">
            <td class="nowrap small">{{ formatDateTime(d.at) }}</td>
            <td><span class="status" :class="d.severity">{{ d.severity_label }}</span></td>
            <td class="small">{{ d.phase_name || '—' }}</td>
            <td class="small">{{ d.message }}<div v-if="d.zones.length" class="faint">зона: {{ d.zones.join(', ') }}</div></td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<style scoped>
.link-row { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; padding: 14px; border: 1px solid var(--hair); border-radius: var(--r-m); background: var(--night); }
.link-row code { font-size: 12.5px; color: var(--accent); word-break: break-all; }
.field.inline { display: flex; align-items: center; gap: 8px; }
.report-card { display: grid; grid-template-columns: 64px 1fr auto; gap: 26px; align-items: center; padding: 34px; border-radius: var(--r-xl); border: 1px solid rgba(205, 183, 143, 0.25); background: linear-gradient(135deg, rgba(205, 183, 143, 0.1), rgba(205, 183, 143, 0.02) 60%), var(--panel); }
.report-card h2 { margin-bottom: 8px; }
.report-card p { margin: 0; color: var(--ink-2); }
.report-icon { width: 64px; height: 64px; border-radius: 50%; border: 1px solid rgba(205, 183, 143, 0.45); color: var(--accent); display: grid; place-items: center; }
.report-icon svg { width: 26px; height: 26px; }
@media (max-width: 800px) { .report-card { grid-template-columns: 1fr; } }
</style>
