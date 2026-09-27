import { createRouter, createWebHistory } from 'vue-router'
import { session } from './store.js'
import LoginView from './views/LoginView.vue'
import ProjectsView from './views/ProjectsView.vue'
import ProjectView from './views/ProjectView.vue'
import BuildingView from './views/BuildingView.vue'

const router = createRouter({
  history: createWebHistory(),
  scrollBehavior: (_to, _from, savedPosition) => savedPosition || { top: 0 },
  routes: [
    { path: '/login', component: LoginView, meta: { public: true } },
    { path: '/', component: ProjectsView },
    { path: '/projects/:id', component: ProjectView, props: (r) => ({ id: Number(r.params.id) }) },
    {
      path: '/buildings/:id/:tab?',
      component: BuildingView,
      props: (r) => ({ id: Number(r.params.id), tab: r.params.tab || 'photos' }),
    },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})

router.beforeEach((to) => {
  if (!to.meta.public && !session.token) return { path: '/login', query: { next: to.fullPath } }
  if (to.path === '/login' && session.token) return '/'
})

export default router
