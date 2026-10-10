<script setup lang="ts">
import { Monitor, Moon, Sun } from 'lucide-vue-next'
import { storeToRefs } from 'pinia'
import {
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuPortal,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuRoot,
  DropdownMenuTrigger,
} from 'reka-ui'

import { useThemeStore, type Tema } from '@/stores/theme'

const { tema } = storeToRefs(useThemeStore())
const opcoes: { valor: Tema; icone: typeof Sun }[] = [
  { valor: 'claro', icone: Sun },
  { valor: 'escuro', icone: Moon },
  { valor: 'automatico', icone: Monitor },
]
</script>

<template>
  <DropdownMenuRoot>
    <DropdownMenuTrigger
      class="inline-flex size-10 items-center justify-center rounded-md text-fg hover:bg-surface-raised"
      :aria-label="$t('tema.titulo')"
    >
      <Sun class="size-5 dark:hidden" aria-hidden="true" />
      <Moon class="hidden size-5 dark:block" aria-hidden="true" />
    </DropdownMenuTrigger>
    <DropdownMenuPortal>
      <DropdownMenuContent
        align="end"
        :side-offset="4"
        class="z-50 min-w-40 rounded-md border border-border bg-surface p-1 text-fg shadow-lg"
      >
        <DropdownMenuLabel class="px-2 py-1 text-xs text-muted">
          {{ $t('tema.titulo') }}
        </DropdownMenuLabel>
        <DropdownMenuRadioGroup v-model="tema">
          <DropdownMenuRadioItem
            v-for="opcao in opcoes"
            :key="opcao.valor"
            :value="opcao.valor"
            class="flex h-8 cursor-default items-center gap-2 rounded px-2 outline-none select-none data-highlighted:bg-surface-raised data-[state=checked]:font-semibold"
          >
            <component :is="opcao.icone" class="size-4" aria-hidden="true" />
            {{ $t(`tema.${opcao.valor}`) }}
          </DropdownMenuRadioItem>
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenuPortal>
  </DropdownMenuRoot>
</template>
