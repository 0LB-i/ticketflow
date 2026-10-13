<script setup lang="ts">
import { Menu, Plus, Search, X } from 'lucide-vue-next'
import {
  DialogClose,
  DialogContent,
  DialogOverlay,
  DialogPortal,
  DialogRoot,
  DialogTitle,
} from 'reka-ui'
import { ref } from 'vue'
import { useRouter } from 'vue-router'

import { useAuthStore } from '@/stores/auth'

import AppLogo from './AppLogo.vue'
import SideNav from './SideNav.vue'
import ThemeMenu from './ThemeMenu.vue'
import UserMenu from './UserMenu.vue'

/** Estrutura geral (docs/13 §13.1): menu lateral, cabeçalho e área de conteúdo. */
const gavetaAberta = ref(false)
const auth = useAuthStore()
const router = useRouter()

/** Busca global (docs/13 §13.1): "1234" ou "#1234" abre o chamado; texto vai para a lista. */
const termo = ref('')
function buscar() {
  const q = termo.value.trim()
  if (!q) return
  const numero = q.replace(/^#/, '')
  termo.value = ''
  if (/^\d+$/.test(numero)) router.push(`/chamados/${numero}`)
  else router.push({ name: 'chamados', query: { aba: 'todos', q } })
}
</script>

<template>
  <a
    href="#conteudo"
    class="sr-only z-50 rounded-md bg-surface px-4 py-2 focus:not-sr-only focus:fixed focus:top-2 focus:left-2"
  >
    {{ $t('app.pularParaConteudo') }}
  </a>

  <div class="flex min-h-dvh">
    <!-- Menu lateral fixo a partir de 768 px -->
    <aside class="hidden w-60 shrink-0 border-r border-border bg-surface md:block">
      <div class="flex h-14 items-center border-b border-border px-4"><AppLogo /></div>
      <SideNav />
    </aside>

    <div class="flex min-w-0 flex-1 flex-col">
      <header
        class="flex h-14 items-center gap-2 border-b border-border bg-surface px-4 md:justify-end"
      >
        <DialogRoot v-model:open="gavetaAberta">
          <button
            type="button"
            class="inline-flex size-10 items-center justify-center rounded-md hover:bg-surface-raised md:hidden"
            :aria-label="$t('app.abrirMenu')"
            @click="gavetaAberta = true"
          >
            <Menu class="size-5" aria-hidden="true" />
          </button>
          <DialogPortal>
            <DialogOverlay class="fixed inset-0 z-40 bg-black/50 md:hidden" />
            <DialogContent
              class="fixed inset-y-0 left-0 z-50 w-72 max-w-[85vw] bg-surface text-fg shadow-xl md:hidden"
            >
              <div class="flex h-14 items-center justify-between border-b border-border px-4">
                <DialogTitle as-child><AppLogo /></DialogTitle>
                <DialogClose
                  class="inline-flex size-10 items-center justify-center rounded-md hover:bg-surface-raised"
                  :aria-label="$t('app.fecharMenu')"
                >
                  <X class="size-5" aria-hidden="true" />
                </DialogClose>
              </div>
              <SideNav @navigate="gavetaAberta = false" />
            </DialogContent>
          </DialogPortal>
        </DialogRoot>
        <span class="md:hidden"><AppLogo /></span>
        <form
          role="search"
          class="hidden max-w-md flex-1 md:mr-auto md:flex"
          @submit.prevent="buscar"
        >
          <label class="relative flex-1">
            <span class="sr-only">{{ $t('app.buscar') }}</span>
            <Search
              class="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted"
              aria-hidden="true"
            />
            <input
              v-model="termo"
              type="search"
              :placeholder="$t('app.buscar')"
              class="h-9 w-full rounded-md border border-border-input bg-surface pr-3 pl-9 text-fg placeholder:text-muted"
            />
          </label>
        </form>
        <div class="ml-auto flex items-center gap-1 md:ml-0">
          <!-- Sempre visível para quem registra chamados (docs/13 §13.1) -->
          <RouterLink
            v-if="auth.pode('ticket.create')"
            to="/chamados/novo"
            class="mr-1 inline-flex h-9 items-center gap-1 rounded-md bg-primary px-3 text-sm font-medium text-on-primary hover:bg-primary-hover"
          >
            <Plus class="size-4" aria-hidden="true" />
            <span class="hidden sm:inline">{{ $t('chamados.novo') }}</span>
            <span class="sr-only sm:hidden">{{ $t('chamados.novo') }}</span>
          </RouterLink>
          <ThemeMenu />
          <UserMenu />
        </div>
      </header>

      <main id="conteudo" tabindex="-1" class="flex-1 p-4 md:p-6">
        <slot />
      </main>
    </div>
  </div>
</template>
