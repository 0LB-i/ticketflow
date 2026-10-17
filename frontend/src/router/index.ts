import {
  createRouter,
  createWebHistory,
  type RouteLocationNormalized,
  type RouteRecordRaw,
} from 'vue-router'

import { useAuthStore } from '@/stores/auth'

declare module 'vue-router' {
  interface RouteMeta {
    /** Acessível sem login (docs/13 §13.3). */
    publica?: boolean
    /** Permissão exigida para abrir a tela. */
    permissao?: string
    /** Usa o layout em cartão, sem menu (telas sem login e a troca obrigatória de senha). */
    cartao?: boolean
    titulo?: string
  }
}

// Telas que já migraram para o servidor (ADR 0011): a SPA recarrega a página nelas.
const NA_SERVIDOR = () => import('@/views/ServerView.vue')

const routes: RouteRecordRaw[] = [
  // A tela inicial é a lista de chamados.
  { path: '/', redirect: { name: 'chamados' } },
  {
    path: '/login',
    name: 'login',
    component: NA_SERVIDOR,
    meta: { publica: true, cartao: true },
  },
  {
    path: '/esqueci-senha',
    name: 'esqueci-senha',
    component: NA_SERVIDOR,
    meta: { publica: true, cartao: true },
  },
  {
    path: '/convite/:token',
    name: 'convite',
    component: NA_SERVIDOR,
    meta: { publica: true, cartao: true },
  },
  {
    path: '/redefinir-senha/:token',
    name: 'redefinir-senha',
    component: NA_SERVIDOR,
    meta: { publica: true, cartao: true },
  },
  {
    path: '/trocar-senha',
    name: 'trocar-senha',
    component: NA_SERVIDOR,
    meta: { cartao: true },
  },
  {
    path: '/chamados',
    name: 'chamados',
    component: () => import('@/views/tickets/TicketsView.vue'),
  },
  {
    path: '/chamados/novo',
    name: 'novo-chamado',
    component: () => import('@/views/tickets/NewTicketView.vue'),
    meta: { permissao: 'ticket.create' },
  },
  {
    path: '/chamados/:numero(\\d+)',
    name: 'chamado',
    component: () => import('@/views/tickets/TicketView.vue'),
    props: true,
  },
  {
    path: '/admin/clientes',
    name: 'clientes',
    component: () => import('@/views/clients/ClientsView.vue'),
    meta: { permissao: 'client.view' },
  },
  {
    path: '/admin/clientes/novo',
    name: 'novo-cliente',
    component: () => import('@/views/clients/ClientFormView.vue'),
    meta: { permissao: 'client.manage' },
  },
  {
    path: '/admin/clientes/:id([0-9a-f-]{36})',
    name: 'cliente',
    component: () => import('@/views/clients/ClientFormView.vue'),
    props: true,
    meta: { permissao: 'client.view' },
  },
  {
    path: '/relatorios',
    name: 'relatorios',
    component: () => import('@/views/reports/ReportsView.vue'),
  },
  {
    path: '/admin/usuarios',
    name: 'admin-usuarios',
    component: () => import('@/views/admin/UsersView.vue'),
    meta: { permissao: 'admin.users' },
  },
  {
    path: '/admin/grupos',
    name: 'admin-grupos',
    component: () => import('@/views/admin/TeamsView.vue'),
    meta: { permissao: 'admin.organization' },
  },
  {
    path: '/admin/setores',
    name: 'admin-setores',
    component: () => import('@/views/admin/DepartmentsView.vue'),
    meta: { permissao: 'admin.organization' },
  },
  {
    path: '/admin/configuracoes',
    name: 'admin-configuracoes',
    component: () => import('@/views/admin/SettingsView.vue'),
    meta: { permissao: 'admin.settings' },
  },
  {
    path: '/sem-acesso',
    name: 'sem-acesso',
    component: () => import('@/views/ForbiddenView.vue'),
  },
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

/** Cria o router com as rotas e a proteção. Os testes criam um por teste. */
export function criarRouter() {
  const router = createRouter({ history: createWebHistory(), routes })
  router.beforeEach(protegerRota)
  return router
}

async function protegerRota(to: RouteLocationNormalized) {
  const auth = useAuthStore()
  if (!auth.carregado) await auth.carregar()

  if (to.meta.publica) {
    // Logado não precisa da tela de login; convite e redefinição continuam acessíveis.
    return to.name === 'login' && auth.logado ? { name: 'chamados' } : true
  }
  if (!auth.logado) {
    // A tela inicial já é o destino padrão depois do login: não precisa de "volta".
    return { name: 'login', query: to.fullPath === '/chamados' ? {} : { volta: to.fullPath } }
  }
  // Senha provisória (admin/admin na instalação): nada abre antes da troca (docs/09 §9.2).
  if (auth.precisaTrocarSenha) {
    return to.name === 'trocar-senha' ? true : { name: 'trocar-senha' }
  }
  if (to.name === 'trocar-senha') return { name: 'chamados' }
  if (to.meta.permissao && !auth.pode(to.meta.permissao)) {
    return { name: 'sem-acesso' }
  }
  return true
}

export const router = criarRouter()
