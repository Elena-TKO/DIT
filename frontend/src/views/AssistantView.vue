<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { api, askAssistant } from '../api.js'
import { ui } from '../store.js'
import { renderMarkdown } from '../lib/chat-format.js'
import Icon from '../components/Icon.vue'

// Помощник по документации (бета). Ответ приходит потоком с сервера и печатается по мере получения.
// База знаний пока демонстрационная: поиск по ключевым словам вместо векторного, шаблоны вместо LLM.
const QUICK = [
  { title: 'Текущий этап', text: 'Опиши текущий этап' },
  { title: 'Причина простоя', text: 'Почему возник простой?' },
  { title: 'Кому звонить', text: 'Контакты ответственных за экскаваторы' },
]

const messages = ref([])
const draft = ref('')
const busy = ref(false)
const error = ref('')
const projects = ref([])
const projectId = ref('')
const docs = ref([])
const docsOpen = ref(false)
const uploading = ref(false)
const scroller = ref(null)
const input = ref(null)
const fileInput = ref(null)
let controller = null
let nextId = 1

const ownDocs = computed(() => docs.value.filter((d) => !d.builtin))
const builtinDocs = computed(() => docs.value.filter((d) => d.builtin))

function scrollDown(force = false) {
  nextTick(() => {
    const box = scroller.value
    if (!box) return
    if (force || box.scrollHeight - box.scrollTop - box.clientHeight < 160) box.scrollTop = box.scrollHeight
  })
}

function autosize() {
  const t = input.value
  if (!t) return
  t.style.height = 'auto'
  t.style.height = Math.min(t.scrollHeight, 180) + 'px'
}

async function send(text = draft.value) {
  const question = text.trim()
  if (!question || busy.value) return
  error.value = ''
  draft.value = ''
  nextTick(autosize)
  messages.value.push({ id: nextId++, role: 'user', text: question })
  const answer = { id: nextId++, role: 'assistant', text: '', sources: [], streaming: true, project: null }
  messages.value.push(answer)
  const msg = messages.value[messages.value.length - 1]   // реактивная копия — её и обновляем
  scrollDown(true)
  busy.value = true
  controller = new AbortController()
  try {
    await askAssistant(question, {
      projectId: projectId.value ? Number(projectId.value) : null,
      signal: controller.signal,
      onMeta: (meta) => { msg.sources = meta.sources || []; msg.project = meta.project },
      onDelta: (piece) => { msg.text += piece; scrollDown() },
    })
  } catch (e) {
    if (e.name === 'AbortError') msg.stopped = true
    else {
      msg.failed = true
      error.value = e.message
      if (!msg.text) msg.text = 'Не удалось получить ответ.'
    }
  } finally {
    msg.streaming = false
    busy.value = false
    controller = null
    scrollDown()
    nextTick(() => input.value?.focus())
  }
}

function stop() {
  controller?.abort()
}

function onKey(event) {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault()
    send()
  }
}

function clearChat() {
  if (busy.value) stop()
  messages.value = []
  error.value = ''
}

async function loadDocs() {
  docs.value = await api.assistantDocuments().catch(() => [])
}

async function upload(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file) return
  uploading.value = true
  error.value = ''
  try {
    const doc = await api.addAssistantDocument(file)
    messages.value.push({
      id: nextId++, role: 'system',
      text: doc.note || `Документ «${doc.name}» добавлен в базу знаний: ${doc.chunks} фрагм. Теперь помощник ищет и в нём.`,
    })
    await loadDocs()
    scrollDown(true)
  } catch (e) {
    error.value = e.message
  } finally {
    uploading.value = false
  }
}

async function removeDoc(doc) {
  if (!window.confirm(`Убрать «${doc.name}» из базы знаний?`)) return
  try {
    await api.deleteAssistantDocument(doc.id)
    await loadDocs()
  } catch (e) {
    error.value = e.message
  }
}

function fileSize(bytes) {
  if (!bytes && bytes !== 0) return ''
  return bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} КБ` : `${(bytes / 1024 / 1024).toFixed(1)} МБ`
}

onMounted(() => {
  Object.assign(ui, { crumbs: [], projectId: null, buildingId: null })
  api.projects().then((list) => { projects.value = list }).catch(() => {})
  loadDocs()
  input.value?.focus()
})
onBeforeUnmount(stop)
</script>

<template>
  <main class="assistant-page">
    <header class="as-heading">
      <div>
        <h1>Помощник <span class="as-beta">бета</span></h1>
        <p>Отвечает по документации стройки: регламентам, журналу работ, контактам. Сейчас работает на демонстрационной базе знаний.</p>
      </div>
      <div class="as-controls">
        <label class="as-context">Стройка
          <select v-model="projectId" :disabled="busy">
            <option value="">Демо-данные</option>
            <option v-for="p in projects" :key="p.id" :value="String(p.id)">{{ p.name }}</option>
          </select>
        </label>
        <button class="btn" type="button" :aria-expanded="docsOpen" @click="docsOpen = !docsOpen">
          <Icon name="report" />База знаний · {{ docs.length }}
        </button>
      </div>
    </header>

    <div class="as-layout" :class="{ 'with-docs': docsOpen }">
      <section class="as-chat" aria-label="Чат с помощником">
        <div ref="scroller" class="as-scroll" aria-live="polite">
          <div v-if="!messages.length" class="as-empty">
            <span class="as-empty-icon"><Icon name="spark" /></span>
            <h2>Спросите о стройке</h2>
            <p>Помощник найдёт ответ в документах и покажет, откуда он взят. Попробуйте один из вопросов:</p>
            <div class="as-quick-cards">
              <button v-for="q in QUICK" :key="q.text" type="button" @click="send(q.text)">
                <b>{{ q.title }}</b><span>{{ q.text }}</span>
              </button>
            </div>
          </div>

          <template v-for="m in messages" :key="m.id">
            <div v-if="m.role === 'user'" class="as-msg user"><p>{{ m.text }}</p></div>
            <div v-else-if="m.role === 'system'" class="as-msg system"><Icon name="clip" /><span>{{ m.text }}</span></div>
            <div v-else class="as-msg bot" :class="{ failed: m.failed }">
              <span class="as-avatar"><Icon name="spark" /></span>
              <div class="as-bubble">
                <span v-if="m.project" class="as-context-tag">По стройке «{{ m.project }}»</span>
                <div v-if="!m.text && m.streaming" class="as-typing" aria-label="Помощник печатает"><i></i><i></i><i></i></div>
                <div v-else class="as-text" :class="{ streaming: m.streaming }" v-html="renderMarkdown(m.text)"></div>
                <span v-if="m.stopped" class="as-note">Ответ остановлен</span>
                <div v-if="m.sources?.length && !m.streaming" class="as-sources">
                  <span>Источники:</span>
                  <span v-for="(s, i) in m.sources" :key="i" class="as-source" :title="s.snippet"><Icon name="report" />{{ s.title }}</span>
                </div>
              </div>
            </div>
          </template>
        </div>

        <div class="as-composer">
          <div v-if="messages.length" class="as-quick">
            <button v-for="q in QUICK" :key="q.text" type="button" :disabled="busy" @click="send(q.text)">{{ q.text }}</button>
            <button type="button" class="as-clear" :disabled="!messages.length" @click="clearChat">Очистить</button>
          </div>
          <p v-if="error" class="error" role="alert">{{ error }}</p>
          <form class="as-input" @submit.prevent="send()">
            <input ref="fileInput" type="file" hidden accept=".txt,.md,.csv,.json,.docx,.xlsx,.pdf" @change="upload" />
            <button class="as-attach" type="button" :disabled="uploading" title="Добавить документ в базу знаний"
              @click="fileInput.click()"><Icon name="clip" /><span>{{ uploading ? 'Загрузка…' : 'Документ' }}</span></button>
            <textarea ref="input" v-model="draft" rows="1" placeholder="Например: не хватает экскаваторов, кому звонить?"
              aria-label="Вопрос помощнику" @keydown="onKey" @input="autosize"></textarea>
            <button v-if="busy" class="as-send stop" type="button" aria-label="Остановить ответ" @click="stop"><Icon name="stop" /></button>
            <button v-else class="as-send" type="submit" :disabled="!draft.trim()" aria-label="Отправить"><Icon name="send" /></button>
          </form>
          <p class="as-disclaimer">Бета-версия: ответы собираются из демонстрационной базы знаний, ФИО и телефоны вымышлены. Проверяйте важные данные.</p>
        </div>
      </section>

      <aside v-if="docsOpen" class="as-docs" aria-label="База знаний">
        <div class="as-docs-head">
          <h2>База знаний</h2>
          <button class="btn small" type="button" :disabled="uploading" @click="fileInput.click()"><Icon name="plus" />Добавить</button>
        </div>
        <p class="as-docs-hint">Текст извлекается из .txt, .md, .csv, .docx, .xlsx. Поиск — по ключевым словам (в бете вместо векторного).</p>
        <template v-if="ownDocs.length">
          <h3>Ваши документы</h3>
          <ul>
            <li v-for="d in ownDocs" :key="d.id">
              <Icon name="report" /><span><b>{{ d.name }}</b><small>{{ fileSize(d.size) }} · {{ d.chunks }} фрагм.</small></span>
              <button type="button" aria-label="Удалить документ" @click="removeDoc(d)"><Icon name="close" /></button>
            </li>
          </ul>
        </template>
        <h3>Демонстрационные</h3>
        <ul>
          <li v-for="d in builtinDocs" :key="d.id">
            <Icon name="report" /><span><b>{{ d.name }}</b><small>{{ d.chunks }} фрагм.</small></span>
          </li>
        </ul>
      </aside>
    </div>
  </main>
</template>

<style>
/* Цвета через переменные: светлый дизайн по умолчанию, классический тёмный — в .design-classic */
.assistant-page { --as-surface:#fff; --as-surface-2:#f6f8fb; --as-line:#dde5ec; --as-ink:#1f2430; --as-muted:#7b8596; --as-accent:#3568f2; --as-accent-soft:#edf2ff; --as-violet:#6f63ff; --as-violet-soft:#f0ebff; --as-danger:#b42336; --as-on-accent:#fff; --as-focus:#4073f41a; --as-serif:Georgia, serif; --as-sans:Inter, "Segoe UI", sans-serif; }
.design-classic :is(.assistant-page) { --as-surface:var(--panel); --as-surface-2:var(--panel-2); --as-line:var(--hair-2); --as-ink:var(--ink); --as-muted:var(--ink-3); --as-accent:var(--accent); --as-accent-soft:var(--accent-soft); --as-violet:var(--accent-2); --as-violet-soft:var(--accent-soft); --as-danger:var(--critical); --as-on-accent:var(--accent-ink); --as-focus:rgba(205, 183, 143, 0.15); --as-serif:var(--serif); --as-sans:var(--font); }
.assistant-page { max-width:1188px; margin:0 auto; padding:42px 56px 32px; min-height:100vh; display:flex; flex-direction:column; }
.as-heading { display:flex; justify-content:space-between; align-items:flex-end; gap:24px; flex-wrap:wrap; margin-bottom:24px; }
.as-heading h1 { font-size:46px; line-height:52px; font-weight:400; display:flex; align-items:center; gap:14px; }
.as-heading p { color:var(--as-muted); font-size:14px; margin:10px 0 0; max-width:620px; }
.as-beta { font:700 12px/1 var(--as-sans); color:var(--as-violet); background:var(--as-violet-soft); border-radius:999px; padding:6px 10px; letter-spacing:.02em; }
.as-controls { display:flex; gap:12px; align-items:flex-end; }
.as-context { display:grid; gap:4px; font-size:12px; color:var(--as-muted); }
.as-context select { min-width:220px; height:40px; }
.as-layout { flex:1; display:grid; grid-template-columns:minmax(0,1fr); gap:24px; min-height:0; }
.as-layout.with-docs { grid-template-columns:minmax(0,1fr) 320px; }
.as-chat { display:flex; flex-direction:column; background:var(--as-surface); border-radius:22px; min-height:560px; height:calc(100vh - 210px); overflow:hidden; }
.as-scroll { flex:1; overflow-y:auto; padding:28px 32px 12px; display:flex; flex-direction:column; gap:18px; }
.as-empty { margin:auto; text-align:center; max-width:640px; padding:24px 0; }
.as-empty-icon { display:inline-grid; place-items:center; width:56px; height:56px; border-radius:18px; background:var(--as-accent-soft); color:var(--as-accent); margin-bottom:16px; }
.as-empty-icon svg { width:26px; height:26px; }
.as-empty h2 { font:400 30px/1.2 var(--as-serif); }
.as-empty p { color:var(--as-muted); font-size:14px; margin:10px 0 24px; }
.as-quick-cards { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px; text-align:left; }
.as-quick-cards button { display:grid; gap:6px; padding:16px; border:1px solid var(--as-line); border-radius:14px; background:var(--as-surface-2); font:inherit; color:var(--as-ink); cursor:pointer; transition:border-color .2s, background .2s; }
.as-quick-cards button:hover { border-color:var(--as-accent); background:var(--as-accent-soft); }
.as-quick-cards b { font-size:13px; }
.as-quick-cards span { font-size:12px; color:var(--as-muted); }
.as-msg { display:flex; gap:12px; max-width:860px; animation:as-in .25s ease-out; }
.as-msg.user { align-self:flex-end; }
.as-msg.user p { margin:0; background:var(--as-accent); color:var(--as-on-accent); padding:11px 16px; border-radius:18px 18px 4px 18px; font-size:14px; line-height:1.5; white-space:pre-wrap; overflow-wrap:anywhere; }
.as-msg.system { align-self:center; align-items:center; gap:8px; font-size:12px; color:var(--as-muted); background:var(--as-surface-2); padding:8px 14px; border-radius:999px; }
.as-msg.system svg { width:14px; height:14px; }
.as-avatar { flex:none; display:grid; place-items:center; width:34px; height:34px; border-radius:11px; background:var(--as-accent-soft); color:var(--as-accent); }
.as-avatar svg { width:18px; height:18px; }
.as-bubble { min-width:0; padding-top:5px; }
.as-context-tag { display:inline-block; font-size:11px; font-weight:700; color:var(--as-violet); margin-bottom:6px; }
.as-text { font-size:14.5px; line-height:1.65; color:var(--as-ink); overflow-wrap:anywhere; }
.as-text p { margin:0 0 10px; }
.as-text ul, .as-text ol { margin:0 0 10px; padding-left:22px; }
.as-text li { margin:3px 0; }
.as-text strong { font-weight:700; }
.as-text em { color:var(--as-muted); }
.as-text > :last-child { margin-bottom:0; }
.as-text.streaming > :last-child::after { content:""; display:inline-block; width:8px; height:15px; margin-left:3px; vertical-align:-2px; background:var(--as-accent); border-radius:2px; animation:as-caret 1s steps(2) infinite; }
.as-msg.failed .as-text { color:var(--as-danger); }
.as-typing { display:flex; gap:5px; padding:8px 0; }
.as-typing i { width:7px; height:7px; border-radius:50%; background:var(--as-muted); animation:as-dot 1.2s infinite ease-in-out; }
.as-typing i:nth-child(2) { animation-delay:.15s; } .as-typing i:nth-child(3) { animation-delay:.3s; }
.as-note { display:block; font-size:12px; color:var(--as-muted); margin-top:6px; }
.as-sources { display:flex; flex-wrap:wrap; gap:6px; align-items:center; margin-top:12px; font-size:11px; color:var(--as-muted); }
.as-source { display:inline-flex; align-items:center; gap:5px; border:1px solid var(--as-line); border-radius:999px; padding:3px 10px; color:var(--as-ink); background:var(--as-surface-2); cursor:help; }
.as-source svg { width:12px; height:12px; color:var(--as-accent); }
.as-composer { border-top:1px solid var(--as-line); padding:14px 24px 16px; background:var(--as-surface-2); }
.as-quick { display:flex; flex-wrap:wrap; gap:8px; margin-bottom:12px; }
.as-quick button { border:1px solid var(--as-line); background:var(--as-surface); border-radius:999px; padding:6px 12px; font:inherit; font-size:12px; color:var(--as-ink); cursor:pointer; }
.as-quick button:hover:not(:disabled) { border-color:var(--as-accent); color:var(--as-accent); }
.as-quick button:disabled { opacity:.5; cursor:default; }
.as-quick .as-clear { margin-left:auto; border-color:transparent; background:none; color:var(--as-muted); }
.as-input { display:flex; align-items:flex-end; gap:10px; background:var(--as-surface); border:1px solid var(--as-line); border-radius:16px; padding:8px; }
.as-input:focus-within { border-color:var(--as-accent); box-shadow:0 0 0 3px var(--as-focus); }
.as-input textarea { flex:1; border:0; resize:none; font:inherit; font-size:14.5px; line-height:1.5; padding:7px 4px; max-height:180px; background:transparent; color:var(--as-ink); outline:none; box-shadow:none; }
.as-attach { display:inline-flex; align-items:center; gap:6px; height:36px; padding:0 10px; border:0; border-radius:10px; background:var(--as-surface-2); color:var(--as-muted); font:inherit; font-size:12px; cursor:pointer; }
.as-attach:hover:not(:disabled) { color:var(--as-accent); background:var(--as-accent-soft); }
.as-attach svg { width:16px; height:16px; }
.as-send { display:grid; place-items:center; width:38px; height:36px; border:0; border-radius:10px; background:var(--as-accent); color:var(--as-on-accent); cursor:pointer; flex:none; }
.as-send:disabled { background:var(--as-line); cursor:default; }
.as-send.stop { background:var(--as-ink); }
.as-send svg { width:17px; height:17px; }
.as-disclaimer { margin:10px 4px 0; font-size:11px; color:var(--as-muted); }
.as-docs { background:var(--as-surface); border-radius:22px; padding:22px; align-self:start; max-height:calc(100vh - 210px); overflow:auto; }
.as-docs-head { display:flex; justify-content:space-between; align-items:center; gap:12px; }
.as-docs-head h2 { font:400 24px/1.2 var(--as-serif); }
.as-docs-hint { font-size:12px; color:var(--as-muted); margin:8px 0 16px; }
.as-docs h3 { font-size:11px; font-weight:700; text-transform:uppercase; color:var(--as-muted); margin:16px 0 8px; }
.as-docs ul { list-style:none; margin:0; padding:0; display:grid; gap:8px; }
.as-docs li { display:flex; align-items:flex-start; gap:10px; padding:10px; border-radius:12px; background:var(--as-surface-2); font-size:12px; }
.as-docs li > svg { width:16px; height:16px; flex:none; color:var(--as-accent); margin-top:2px; }
.as-docs li span { flex:1; display:grid; gap:2px; min-width:0; }
.as-docs li b { font-weight:600; overflow-wrap:anywhere; }
.as-docs li small { color:var(--as-muted); }
.as-docs li button { background:none; border:0; color:var(--as-muted); cursor:pointer; padding:0; }
.as-docs li button svg { width:14px; height:14px; }
@keyframes as-in { from { opacity:0; transform:translateY(6px); } to { opacity:1; transform:none; } }
@keyframes as-caret { 50% { opacity:0; } }
@keyframes as-dot { 0%, 80%, 100% { transform:scale(.6); opacity:.4; } 40% { transform:scale(1); opacity:1; } }
@media(max-width:1100px) { .as-layout.with-docs { grid-template-columns:1fr; } .as-docs { max-height:none; } }
@media(max-width:760px) { .assistant-page { padding:28px 16px 24px; } .as-heading h1 { font-size:36px; } .as-quick-cards { grid-template-columns:1fr; } .as-scroll { padding:20px 16px 8px; } .as-composer { padding:12px; } .as-attach span { display:none; } .as-chat { height:calc(100vh - 160px); } }
@media (prefers-reduced-motion: reduce) { .as-msg, .as-typing i, .as-text.streaming > :last-child::after { animation:none; } }
</style>
