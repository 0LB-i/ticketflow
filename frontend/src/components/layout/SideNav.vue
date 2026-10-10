<script setup lang="ts">
import {
  Building2,
  FolderTree,
  House,
  LayoutGrid,
  Ticket,
  Users,
  UsersRound,
} from 'lucide-vue-next'
import { computed } from 'vue'

import { useAuthStore } from '@/stores/auth'

defineEmits<{ navigate: [] }>()

const auth = useAuthStore()

const principal = [
  { to: '/', rotulo: 'menu.inicio', icone: House },
  { to: '/chamados', rotulo: 'menu.chamados', icone: Ticket },
]
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
      to: '/admin/categorias',
      rotulo: 'menu.categorias',
      icone: FolderTree,
      perm: 'admin.catalog',
    },
  ].filter((item) => auth.pode(item.perm)),
)
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
          class="flex h-10 items-center gap-3 rounded-md px-3 font-medium text-fg hover:bg-surface-raised"
          exact-active-class="bg-primary-subtle text-primary"
          @click="$emit('navigate')"
        >
          <component :is="item.icone" class="size-5" aria-hidden="true" />
          {{ $t(item.rotulo) }}
        </RouterLink>
      </div>
    </template>
  </nav>
</template>
