<script setup lang="ts">
import { ChevronDown, LogOut } from 'lucide-vue-next'
import {
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuPortal,
  DropdownMenuRoot,
  DropdownMenuTrigger,
} from 'reka-ui'
import { useRouter } from 'vue-router'

import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const router = useRouter()

async function sair() {
  await auth.sair()
  await router.push({ name: 'login' })
}
</script>

<template>
  <DropdownMenuRoot v-if="auth.me">
    <DropdownMenuTrigger
      class="inline-flex h-10 items-center gap-2 rounded-md px-2 text-fg hover:bg-surface-raised"
      :aria-label="$t('usuario.menu')"
    >
      <span
        class="inline-flex size-8 items-center justify-center rounded-full bg-primary-subtle font-semibold text-primary"
        aria-hidden="true"
      >
        {{ auth.me.full_name.charAt(0) }}
      </span>
      <span class="hidden max-w-40 truncate sm:inline">{{ auth.me.full_name }}</span>
      <ChevronDown class="size-4 text-muted" aria-hidden="true" />
    </DropdownMenuTrigger>
    <DropdownMenuPortal>
      <DropdownMenuContent
        align="end"
        :side-offset="4"
        class="z-50 min-w-48 rounded-md border border-border bg-surface p-1 text-fg shadow-lg"
      >
        <DropdownMenuLabel class="px-2 py-1">
          <span class="block font-medium">{{ auth.me.full_name }}</span>
          <span class="block text-xs text-muted">{{ auth.me.email ?? auth.me.username }}</span>
        </DropdownMenuLabel>
        <DropdownMenuItem
          class="flex h-8 cursor-default items-center gap-2 rounded px-2 outline-none select-none data-highlighted:bg-surface-raised"
          @select="sair"
        >
          <LogOut class="size-4" aria-hidden="true" />
          {{ $t('usuario.sair') }}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenuPortal>
  </DropdownMenuRoot>
</template>
