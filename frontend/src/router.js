import { defineComponent, h } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import { session, ui } from './store.js'
import LoginView from './views/LoginView.vue'
import ProjectsView from './views/ProjectsView.vue'
import ProjectView from './views/ProjectView.vue'
import BuildingView from './views/BuildingView.vue'
import AssistantView from './views/AssistantView.vue'
import StageView from './views/StageView.vue'
import ClassicLoginView from './views/classic/ClassicLoginView.vue'
import ClassicProjectsView from './views/classic/ClassicProjectsView.vue'
import ClassicBuildingView from './views/classic/ClassicBuildingView.vue'

/** Экран, который выбирается по дизайну (ui.design); props маршрута передаются как есть. */
function byDesign(name, light, classic) {
  return defineComponent({
    name,
    inheritAttrs: false,
    setup(_, { attrs }) {
      return () => h(ui.design === 'classic' ? classic : light, { ...attrs, key: ui.design })
    },
  })
}
const LoginPage = byDesign('LoginPage', LoginView, ClassicLoginView)
const ProjectsPage = byDesign('ProjectsPage', ProjectsView, ClassicProjectsView)
const BuildingPage = byDesign('BuildingPage', BuildingView, ClassicBuildingView)

const router = createRouter({
  history: createWebHistory(),
  scrollBehavior: (_to, _from, savedPosition) => savedPosition || { top: 0 },
  routes: [
    { path: '/login', component: LoginPage, meta: { public: true } },
    { path: '/', component: ProjectsPage },
    { path: '/projects/:id', component: ProjectView, props: (r) => ({ id: Number(r.params.id) }) },
    {
      path: '/buildings/:id/:tab?',
      component: BuildingPage,
      props: (r) => ({ id: Number(r.params.id), tab: r.params.tab || 'photos' }),
    },
    {
      path: '/buildings/:id/stages/:phase',
      component: StageView,
      props: (r) => ({ id: Number(r.params.id), phase: String(r.params.phase) }),
    },
    { path: '/assistant', component: AssistantView },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})

router.beforeEach((to) => {
  if (!to.meta.public && !session.token) return { path: '/login', query: { next: to.fullPath } }
  if (to.path === '/login' && session.token) return '/'
})

export default router
