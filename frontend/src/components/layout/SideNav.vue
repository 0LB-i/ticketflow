<script setup lang="ts">
import {
  Building2,
  Contact,
  LayoutGrid,
  Settings,
  Ticket,
  Users,
  UsersRound,
} from 'lucide-vue-next'
import { computed } from 'vue'
import { useRoute } from 'vue-router'

import { useAuthStore } from '@/stores/auth'

defineEmits<{ navigate: [] }>()

const auth = useAuthStore()
const route = useRoute()

const principal = computed(() =>
  [
    { to: '/chamados', rotulo: 'menu.chamados', icone: Ticket, perm: null },
    { to: '/clientes', rotulo: 'menu.clientes', icone: Contact, perm: 'client.view' },
  ].filter((item) => !item.perm || auth.pode(item.perm)),
)
const administracao = computed(() =>
  [
    { to: '/admin/usuarios', rotulo: 'menu.usuarios', icone: Users, perm: 'admin.users' },
    { to: '/admin/grupos', rotulo: 'menu.grupos', icone: UsersRound, perm: 'admin.organization' },
    {
      to: '/admin/setores',
      rotulo: 'menu.setores',
      icone: Building2,
      perm: 'admin.organization',
    },
    {
      to: '/admin/configuracoes',
      rotulo: 'menu.configuracoes',
      icone: Settings,
      perm: 'admin.settings',
    },
  ].filter((item) => auth.pode(item.perm)),
)

/** As rotas são planas, então o vue-router não marca "Chamados" em /chamados/123: compara o caminho. */
function ativo(to: string) {
  return route.path === to || route.path.startsWith(`${to}/`)
}

const dev = import.meta.env.DEV
  ? [{ to: '/dev/componentes', rotulo: 'menu.componentes', icone: LayoutGrid }]
  : []
</script>

<template>
  <nav :aria-label="$t('menu.titulo')" class="flex flex-col gap-4 p-3">
    <template
      v-for="(secao, i) in [
        { titulo: null, itens: principal },
        { titulo: 'menu.administracao', itens: administracao },
        { titulo: null, itens: dev },
      ]"
      :key="i"
    >
      <div v-if="secao.itens.length" class="flex flex-col gap-1">
        <p v-if="secao.titulo" class="px-3 pb-1 text-xs font-semibold text-muted uppercase">
          {{ $t(secao.titulo) }}
        </p>
        <RouterLink
          v-for="item in secao.itens"
          :key="item.to"
          :to="item.to"
          class="flex h-10 items-center gap-3 rounded-md px-3 font-medium"
          :class="
            ativo(item.to) ? 'bg-primary-subtle text-primary' : 'text-fg hover:bg-surface-raised'
          "
          :aria-current="ativo(item.to) ? 'page' : undefined"
          @click="$emit('navigate')"
        >
          <component :is="item.icone" class="size-5" aria-hidden="true" />
          {{ $t(item.rotulo) }}
        </RouterLink>
      </div>
    </template>
  </nav>
</template>
