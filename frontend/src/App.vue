<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, imageUrl } from './api.js'
import { session, setSession, ui } from './store.js'
import Icon from './components/Icon.vue'
import DesignSwitch from './components/DesignSwitch.vue'

const route = useRoute()
const router = useRouter()
const projects = ref([])
const buildings = ref([])

const withShell = computed(() => Boolean(session.token) && !route.meta.public)
const initials = computed(() => (session.user?.name || '?').split(/\s+/).map((w) => w[0]).slice(0, 2).join('').toUpperCase())

async function loadNav() {
  if (!session.token) return
  projects.value = await api.projects().catch(() => [])
  buildings.value = ui.projectId ? await api.overview(ui.projectId).then((o) => o.buildings).catch(() => []) : []
}

function logout() {
  setSession(null)
  router.push('/login')
}

watch(() => [session.token, ui.projectId, ui.navVersion], loadNav, { immediate: true })
</script>

<template>
  <div v-if="withShell" class="shell" :class="ui.design === 'classic' ? 'design-classic' : 'projects-light'">
    <aside class="sidebar">
      <RouterLink to="/" class="brand">
        <span class="brand-mark"><Icon name="crane" /></span><span class="brand-name">СтройКонтроль</span>
      </RouterLink>
      <nav class="nav-group" aria-label="Стройки">
        <div class="nav-title">Стройки</div>
        <template v-for="p in projects" :key="p.id">
          <RouterLink :to="`/projects/${p.id}`" class="nav-link" :class="{ active: ui.projectId === p.id && !ui.buildingId }">
            <span class="nav-thumb"><img v-if="p.cover_photo_id" :src="imageUrl(p.cover_photo_id, 120)" alt="" /></span>{{ p.name }}
          </RouterLink>
          <div v-if="ui.projectId === p.id && buildings.length" class="nav-sub">
            <RouterLink v-for="b in buildings" :key="b.id" :to="`/buildings/${b.id}/${ui.design === 'classic' ? 'analysis' : 'photos'}`" class="nav-link"
              :class="{ active: ui.buildingId === b.id }">
              <span class="dot" :class="b.photos ? b.status : ''"></span>{{ b.name }}
            </RouterLink>
            <div v-if="ui.buildingId && ui.design !== 'classic'" class="building-nav">
              <RouterLink :to="`/buildings/${ui.buildingId}/photos`">Фото и техника</RouterLink>
              <RouterLink :to="`/buildings/${ui.buildingId}/plan`" :class="{ 'router-link-active': route.path.includes('/stages/') }">План работ</RouterLink>
              <RouterLink :to="`/buildings/${ui.buildingId}/report`">Отчёт</RouterLink>
            </div>
          </div>
        </template>
        <RouterLink to="/?new=1" class="nav-link new-link">
          <span class="nav-thumb plus"><Icon name="plus" /></span>Новая стройка
        </RouterLink>
        <RouterLink to="/assistant" class="nav-link assistant-link" active-class="active">
          <span class="assistant-icon"><Icon name="spark" /></span>Помощник<span class="beta-tag">β</span>
        </RouterLink>
      </nav>
      <DesignSwitch class="sidebar-design" />
      <div class="sidebar-foot">
        <span class="avatar">{{ initials }}</span>
        <span class="who"><b>{{ session.user?.name }}</b>{{ session.user?.email }}</span>
        <button class="btn ghost small" type="button" aria-label="Выйти" @click="logout"><Icon name="logout" /></button>
      </div>
    </aside>
    <div class="main"><RouterView /></div>
  </div>
  <template v-else>
    <RouterView />
    <DesignSwitch v-if="route.meta.public" floating />
  </template>
</template>

<style src="./projects-light.css"></style>
<style src="./workspace-light.css"></style>

<style>
.nav-thumb.plus { display: grid; place-items: center; background: transparent; border: 1px dashed var(--hair-2); color: var(--ink-3); }
.nav-thumb.plus svg { width: 14px; height: 14px; }
.assistant-link { margin-top: 18px; border-top: 1px solid var(--hair); padding-top: 18px !important; font-weight: 700; color: var(--ink) !important; }
.assistant-link.active { color: #3568f2 !important; background: transparent !important; }
.assistant-icon { display: inline-grid; place-items: center; width: 16px; margin-right: 10px; color: #3568f2; }
.assistant-icon svg { width: 16px; height: 16px; }
.sidebar-design { margin: 0 0 14px; }
.design-classic .assistant-link { color: var(--ink) !important; }
.design-classic .assistant-link.active { color: var(--accent) !important; }
.design-classic .assistant-icon { color: var(--accent); }
.design-classic .beta-tag { color: var(--accent-ink); background: var(--accent); }
@media (max-width: 760px) { .assistant-link { margin-top: 0; border-top: 0; padding-top: 10px !important; } }
.beta-tag { margin-left: 8px; font-size: 10px; font-weight: 700; color: #6f63ff; background: #f0ebff; border-radius: 999px; padding: 1px 7px; }
</style>
