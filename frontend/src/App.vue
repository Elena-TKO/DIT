<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, imageUrl } from './api.js'
import { session, setSession, ui } from './store.js'
import Icon from './components/Icon.vue'

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
  <div v-if="withShell" class="shell">
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
            <RouterLink v-for="b in buildings" :key="b.id" :to="`/buildings/${b.id}/analysis`" class="nav-link"
              :class="{ active: ui.buildingId === b.id }">
              <span class="dot" :class="b.photos ? b.status : ''"></span>{{ b.name }}
            </RouterLink>
          </div>
        </template>
        <RouterLink to="/?new=1" class="nav-link new-link">
          <span class="nav-thumb plus"><Icon name="plus" /></span>Новая стройка
        </RouterLink>
      </nav>
      <div class="sidebar-foot">
        <span class="avatar">{{ initials }}</span>
        <span class="who"><b>{{ session.user?.name }}</b>{{ session.user?.email }}</span>
        <button class="btn ghost small" type="button" aria-label="Выйти" @click="logout"><Icon name="logout" /></button>
      </div>
    </aside>
    <div class="main"><RouterView /></div>
  </div>
  <RouterView v-else />
</template>

<style>
.nav-thumb.plus { display: grid; place-items: center; background: transparent; border: 1px dashed var(--hair-2); color: var(--ink-3); }
.nav-thumb.plus svg { width: 14px; height: 14px; }
</style>
