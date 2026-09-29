<script setup>
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../../api.js'
import { setSession } from '../../store.js'
import Icon from '../../components/Icon.vue'

const route = useRoute()
const router = useRouter()
const mode = ref('login')
const email = ref('')
const password = ref('')
const name = ref('')
const error = ref('')
const busy = ref(false)

async function submit() {
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
  <main class="login">
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
      <form class="stack" @submit.prevent="submit">
        <div>
          <h2>{{ mode === 'login' ? 'Вход' : 'Регистрация' }}</h2>
          <p class="muted small">
            {{ mode === 'login' ? 'Нет аккаунта?' : 'Уже зарегистрированы?' }}
            <button type="button" class="link" @click="mode = mode === 'login' ? 'register' : 'login'">
              {{ mode === 'login' ? 'Создать' : 'Войти' }}
            </button>
          </p>
        </div>
        <label v-if="mode === 'register'" class="field">Имя
          <input v-model="name" autocomplete="name" placeholder="Иван Петров" />
        </label>
        <label class="field">E-mail
          <input v-model="email" type="email" required autocomplete="email" placeholder="name@company.ru" />
        </label>
        <label class="field">Пароль
          <input v-model="password" type="password" required minlength="6"
            :autocomplete="mode === 'login' ? 'current-password' : 'new-password'" />
        </label>
        <p v-if="error" class="error" role="alert">{{ error }}</p>
        <button class="btn primary wide" type="submit" :disabled="busy">
          {{ mode === 'login' ? 'Войти' : 'Создать аккаунт' }}
        </button>
      </form>
    </section>
  </main>
</template>

<style scoped>
.login { position: relative; min-height: 100vh; display: grid; grid-template-columns: minmax(0, 1fr) 440px; grid-template-rows: auto 1fr; gap: 0 64px; padding: 36px 56px 56px; overflow: hidden; }
.login-bg { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; animation: drift 2.8s var(--ease) both; }
@keyframes drift { from { transform: scale(1.08); opacity: 0.4; } to { transform: scale(1); opacity: 1; } }
.login-shade { position: absolute; inset: 0; background: linear-gradient(90deg, rgba(10, 14, 16, 0.9) 0%, rgba(10, 14, 16, 0.55) 55%, rgba(10, 14, 16, 0.75) 100%), linear-gradient(0deg, rgba(10, 14, 16, 0.7), rgba(10, 14, 16, 0) 40%); }
.login-brand, .login-copy, .login-card { position: relative; z-index: 1; }
.login-brand { grid-column: 1 / -1; display: flex; align-items: center; gap: 12px; }
.login-copy { align-self: end; max-width: 640px; }
.login-copy h1 { font-size: 72px; line-height: 0.98; margin-bottom: 24px; }
.login-copy p { font-size: 16px; color: rgba(236, 235, 230, 0.75); max-width: 46ch; margin: 0; }
.login-card { align-self: end; padding: 36px; border-radius: var(--r-xl); background: rgba(13, 18, 21, 0.62); border: 1px solid rgba(236, 235, 230, 0.12); backdrop-filter: blur(22px); -webkit-backdrop-filter: blur(22px); box-shadow: var(--shadow); }
.login-card h2 { font-size: 36px; margin-bottom: 6px; }
.login-card input { background: rgba(5, 8, 9, 0.5); }
.link { font: inherit; color: var(--accent); background: none; border: 0; padding: 0; cursor: pointer; }
.link:hover { color: var(--accent-2); }
.wide { width: 100%; min-height: 48px; }
@media (max-width: 1000px) {
  .login { grid-template-columns: 1fr; padding: 24px 20px 32px; gap: 32px; }
  .login-copy h1 { font-size: 42px; }
  .login-card { padding: 24px; }
}
</style>
