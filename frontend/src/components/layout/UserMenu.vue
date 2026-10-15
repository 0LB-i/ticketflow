<script setup lang="ts">
import { ChevronDown, Languages, LogOut } from 'lucide-vue-next'
import {
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuPortal,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuRoot,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from 'reka-ui'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'

import { useToast } from '@/composables/useToast'
import { type Idioma, IDIOMAS } from '@/i18n'
import { useAuthStore } from '@/stores/auth'
import { useBrandingStore } from '@/stores/branding'

const auth = useAuthStore()
const branding = useBrandingStore()
const router = useRouter()
const toast = useToast()
const { t } = useI18n()

// "padrao" segue o idioma do sistema, definido nas configurações (docs/13).
const PADRAO = 'padrao'
const idioma = computed({
  get: () => auth.me?.locale ?? PADRAO,
  set: async (valor: string) => {
    try {
      await auth.mudarIdioma(valor === PADRAO ? null : (valor as Idioma))
    } catch (e) {
      toast.show({ title: (e as Error).message, variant: 'error' })
    }
  },
})
const opcoes = computed(() => [
  {
    valor: PADRAO,
    rotulo: t('idioma.padraoDoSistema', { idioma: t(`idioma.nomes.${branding.idiomaPadrao}`) }),
  },
  ...IDIOMAS.map((i) => ({ valor: i, rotulo: t(`idioma.nomes.${i}`) })),
])

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
        {{ auth.me.display_name.charAt(0) }}
      </span>
      <span class="hidden max-w-40 truncate sm:inline">{{ auth.me.display_name }}</span>
      <ChevronDown class="size-4 text-muted" aria-hidden="true" />
    </DropdownMenuTrigger>
    <DropdownMenuPortal>
      <DropdownMenuContent
        align="end"
        :side-offset="4"
        class="z-50 min-w-48 rounded-md border border-border bg-surface p-1 text-fg shadow-lg"
      >
        <DropdownMenuLabel class="px-2 py-1">
          <span class="block font-medium">{{ auth.me.display_name }}</span>
          <span class="block text-xs text-muted">{{ auth.me.email ?? auth.me.username }}</span>
        </DropdownMenuLabel>
        <DropdownMenuSeparator class="my-1 h-px bg-border" />
        <DropdownMenuLabel class="flex items-center gap-2 px-2 py-1 text-xs text-muted">
          <Languages class="size-4" aria-hidden="true" />
          {{ $t('idioma.titulo') }}
        </DropdownMenuLabel>
        <DropdownMenuRadioGroup v-model="idioma">
          <DropdownMenuRadioItem
            v-for="opcao in opcoes"
            :key="opcao.valor"
            :value="opcao.valor"
            class="flex h-8 cursor-default items-center rounded px-2 pl-8 outline-none select-none data-highlighted:bg-surface-raised data-[state=checked]:font-semibold"
          >
            {{ opcao.rotulo }}
          </DropdownMenuRadioItem>
        </DropdownMenuRadioGroup>
        <DropdownMenuSeparator class="my-1 h-px bg-border" />
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
