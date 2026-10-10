import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

import HomeView from '@/views/HomeView.vue'

const routes: RouteRecordRaw[] = [
  { path: '/', name: 'inicio', component: HomeView },
  {
    path: '/:caminho(.*)*',
    name: 'nao-encontrado',
    component: () => import('@/views/NotFoundView.vue'),
  },
]

if (import.meta.env.DEV) {
  routes.unshift({
    path: '/dev/componentes',
    name: 'componentes',
    component: () => import('@/views/ComponentsView.vue'),
  })
}

export const router = createRouter({ history: createWebHistory(), routes })
