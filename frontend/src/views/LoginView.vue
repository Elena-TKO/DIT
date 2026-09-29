<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api.js'
import { setSession } from '../store.js'
import Icon from '../components/Icon.vue'

const route = useRoute()
const router = useRouter()
const mode = ref('login')
const email = ref('')
const password = ref('')
const name = ref('')
const error = ref('')
const busy = ref(false)
const page = ref(null)
let scrollFrame = 0
let reducedMotion

function updateScroll() {
  scrollFrame = 0
  const progress = reducedMotion?.matches ? 0 : Math.min(Math.max(window.scrollY / 180, 0), 1)
  const style = page.value?.style
  if (!style) return
  style.setProperty('--image-y', `${60 * progress}px`)
  style.setProperty('--gradient-x', `${18 * progress}px`)
  style.setProperty('--gradient-y', `${25 * progress}px`)
  style.setProperty('--gradient-strength', `${progress * .7}`)
  style.setProperty('--title-x', `${-8 * progress}px`)
  style.setProperty('--title-y', `${35 * progress}px`)
  style.setProperty('--login-y', `${-20 * progress}px`)
}

function scheduleScroll() {
  if (!scrollFrame) scrollFrame = window.requestAnimationFrame(updateScroll)
}

onMounted(() => {
  reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)')
  reducedMotion.addEventListener('change', scheduleScroll)
  window.addEventListener('scroll', scheduleScroll, { passive: true })
  updateScroll()
})

onUnmounted(() => {
  window.removeEventListener('scroll', scheduleScroll)
  reducedMotion?.removeEventListener('change', scheduleScroll)
  window.cancelAnimationFrame(scrollFrame)
})

async function submit() {
  if (busy.value) return
  error.value = ''
  busy.value = true
  try {
    const data = mode.value === 'login'
      ? await api.login(email.value, password.value)
      : await api.register(email.value, password.value, name.value)
    setSession(data)
    router.push(route.query.next || '/')
  } catch (e) {
    error.value = e.message
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <main ref="page" class="login">
    <img class="login-bg" src="/login.jpg" alt="" />
    <div class="login-shade" aria-hidden="true"></div>
    <header class="login-brand">
      <span class="brand-mark"><Icon name="crane" /></span><span class="brand-name">СтройКонтроль</span>
    </header>
    <section class="login-copy">
      <h1>Площадка под контролем каждые тридцать минут</h1>
      <p>Техника на снимках камер сверяется с графиком работ. Этап, отклонения и прогноз срока — без выезда на объект.</p>
    </section>
    <section class="login-card">
      <form class="stack" :aria-busy="busy" @submit.prevent="submit">
        <div>
          <h2>{{ mode === 'login' ? 'Вход' : 'Регистрация' }}</h2>
          <p class="muted small">
            {{ mode === 'login' ? 'Нет аккаунта?' : 'Уже зарегистрированы?' }}
            <button type="button" class="link" :disabled="busy" @click="mode = mode === 'login' ? 'register' : 'login'; error = ''">
              {{ mode === 'login' ? 'Создать' : 'Войти' }}
            </button>
          </p>
        </div>
        <label v-if="mode === 'register'" class="field">Имя
          <input v-model="name" autocomplete="name" placeholder="Иван Петров" :disabled="busy" />
        </label>
        <label class="field">E-mail
          <input v-model="email" type="email" required autocomplete="email" placeholder="name@company.ru" :disabled="busy" />
        </label>
        <label class="field">Пароль
          <input v-model="password" type="password" required minlength="6" :disabled="busy"
            :autocomplete="mode === 'login' ? 'current-password' : 'new-password'" />
        </label>
        <p v-if="error" class="error" role="alert">{{ error }}</p>
        <button class="btn primary wide" type="submit" :disabled="busy">
          {{ busy ? 'Подождите…' : mode === 'login' ? 'Войти' : 'Создать аккаунт' }}
        </button>
      </form>
    </section>
  </main>
</template>

<style scoped>
.login { --ink:#182027; --ink-2:#5f6b75; --ink-3:#8a949d; --accent:#356df3; --accent-2:#2459d6; --critical:#b42336; color-scheme:light; color:var(--ink); background:#f6f8fb; font-family:Onest,"Segoe UI",sans-serif; position:relative; min-height:100vh; min-height:100dvh; display:grid; grid-template-columns:minmax(0,640px) 440px; grid-template-rows:37px auto; align-content:start; gap:145px 80px; padding:36px 56px 56px; overflow:hidden; }
.login { min-height:calc(100dvh + 180px); }
.login-bg { position:absolute; inset:-70px 0 auto; width:100%; height:calc(100% + 140px); object-fit:cover; transform:translate3d(0,var(--image-y, 0px),0) scale(1.035); transform-origin:center top; }
.login-shade { position:absolute; inset:0 0 auto; height:1250px; background:radial-gradient(circle at 30% 32%,rgba(255,255,255,.25),transparent 58%),linear-gradient(90deg,rgba(246,248,251,.88) 0%,rgba(246,248,251,.65) 32%,rgba(246,248,251,.35) 58%,rgba(246,248,251,.18) 100%),linear-gradient(0deg,#f6f8fb 0%,rgba(246,248,251,.8) 12%,transparent 60%); transform:translate3d(var(--gradient-x, 0px),var(--gradient-y, 0px),0) scale(1.08); }
.login-shade { inset:-40px; height:auto; pointer-events:none; }
.login-shade::after { content:""; position:absolute; inset:0; background:linear-gradient(110deg,#f6f8fb 10%,rgba(246,248,251,.85) 55%,rgba(246,248,251,.5)); opacity:var(--gradient-strength, 0); }
.login-brand, .login-copy, .login-card { position: relative; z-index: 1; }
.login-brand { grid-column: 1 / -1; display: flex; align-items: center; gap: 12px; }
.login-brand .brand-mark { border-color:#8a949d; color:#182027; }
.login-brand .brand-name { font-weight:700; font-size:23px; line-height:37px; }
.login-copy { align-self:start; margin-top:107px; max-width:640px; transform:translate3d(var(--title-x, 0px),var(--title-y, 0px),0); }
.login-copy h1 { font-size:72px; line-height:71px; letter-spacing:-.72px; margin-bottom:24px; }
.login-copy p { font-size:16px; line-height:26px; color:#5f6b75; max-width:490px; margin:0; }
.login-card { align-self:start; padding:36px; border-radius:22px; background:rgba(255,255,255,.94); border:1px solid #eef2f6; box-shadow:0 40px 80px -40px rgba(24,32,39,.28); backdrop-filter:blur(22px); transform:translate3d(0,var(--login-y, 0px),0) scale(var(--login-scale, 1)); }
.login-card .stack { display:flex; flex-direction:column; gap:22px; }
.login-card .stack > * { margin:0; }
.login-card h2 { font-size:36px; line-height:40px; margin-bottom:6px; }
.login-card .muted { color:#8a949d; margin:0; }
.login-card .field { color:#8a949d; line-height:20px; gap:7px; }
.login-card input { background:#eef2f6; border:1px solid #eef2f6; height:44px; color:#182027; }
.login-card input:focus { background:#fff; border-color:#356df3; box-shadow:0 0 0 3px #356df31a; }
.login-card .btn.primary { background:#356df3; border-color:#356df3; color:#fff; }
.login-card .btn.primary:hover { background:#2459d6; border-color:#2459d6; }
.link { font: inherit; color: var(--accent); background: none; border: 0; padding: 0; cursor: pointer; }
.link:hover { color: var(--accent-2); }
.link:disabled { opacity:.5; cursor:wait; }
.wide { width: 100%; min-height: 48px; }
@media (max-width: 1000px) {
  .login { grid-template-columns:1fr; grid-template-rows:auto; min-height:calc(100dvh + 120px); padding:24px 20px 80px; gap:32px; }
  .login-copy { margin-top:0; transform:translate3d(0,calc(var(--title-y, 0px) * .25),0); }
  .login-copy h1 { font-size:42px; line-height:1.05; }
  .login-card { padding:24px; width:100%; max-width:440px; transform:translate3d(0,calc(var(--login-y, 0px) * .2),0); }
}
@media (prefers-reduced-motion: reduce) {
  .login-bg, .login-shade, .login-copy, .login-card { transform:none; }
}
</style>
