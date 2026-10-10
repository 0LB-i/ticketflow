<script setup lang="ts">
import { computed, reactive, ref, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { api, ou } from '@/api/client'
import AppLogo from '@/components/layout/AppLogo.vue'
import Button from '@/components/ui/Button.vue'
import SelectField from '@/components/ui/SelectField.vue'
import { useHead } from '@/composables/useHead'
import { useToast } from '@/composables/useToast'
import { type Idioma, IDIOMAS } from '@/i18n'
import { useBrandingStore } from '@/stores/branding'
import { CORES_PADRAO, type Cores, paleta, PREDEFINIDAS, variaveis } from '@/tema/paleta'

/** Configurações da instalação (docs/13: /admin/configuracoes): idioma, cores e logotipo. */
useHead('configuracoes.titulo')
const { t } = useI18n()
const toast = useToast()
const branding = useBrandingStore()
const arquivo = useTemplateRef('arquivo')

const HEX = /^#[0-9a-f]{6}$/i
const LOGO_MAX = 256 * 1024
const LOGO_TIPOS = ['image/png', 'image/jpeg', 'image/webp']

const idioma = ref<Idioma>(branding.idiomaPadrao)
const cores = reactive<Cores>({ ...(branding.dados?.colors ?? CORES_PADRAO) })
const erro = ref<string | null>(null)
const salvando = ref(false)

const CAMPOS = [
  { chave: 'brand', rotulo: 'configuracoes.corMarca', dica: 'configuracoes.corMarcaDica' },
  { chave: 'neutral', rotulo: 'configuracoes.corNeutra', dica: 'configuracoes.corNeutraDica' },
  { chave: 'background', rotulo: 'configuracoes.corFundo', dica: 'configuracoes.corFundoDica' },
] as const

const validas = computed(() => CAMPOS.every((c) => HEX.test(cores[c.chave])))
// Enquanto alguma cor está incompleta, a prévia mostra a última combinação válida.
const ultimaValida = ref<Cores>({ ...cores })
watch(cores, () => {
  if (validas.value) ultimaValida.value = { ...cores }
})
const previa = computed(() => paleta(ultimaValida.value))
const corAjustada = computed(() =>
  previa.value.claro.primary.toUpperCase() !== ultimaValida.value.brand.toUpperCase()
    ? previa.value.claro.primary
    : null,
)
const opcoesIdioma = computed(() =>
  IDIOMAS.map((i) => ({ value: i, label: t(`idioma.nomes.${i}`) })),
)

const iguais = (a: Cores) => CAMPOS.every((c) => cores[c.chave].toUpperCase() === a[c.chave])
const iguaisAoPadrao = () => iguais(CORES_PADRAO)

function usarPredefinida(predefinida: Cores) {
  Object.assign(cores, predefinida)
}

async function salvar() {
  erro.value = null
  salvando.value = true
  try {
    const resultado = ou(
      await api.PATCH('/api/v1/admin/settings', {
        body: { default_locale: idioma.value, colors: iguaisAoPadrao() ? null : { ...cores } },
      }),
      t('comum.erroInesperado'),
    )
    branding.aplicar(resultado)
    toast.show({ title: t('comum.salvo') })
  } catch (e) {
    erro.value = (e as Error).message
  } finally {
    salvando.value = false
  }
}

// --- logotipo ---
const erroLogo = ref<string | null>(null)

function lerComoDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const leitor = new FileReader()
    leitor.onload = () => resolve(String(leitor.result))
    leitor.onerror = () => reject(leitor.error)
    leitor.readAsDataURL(file)
  })
}

async function enviarLogo(evento: Event) {
  erroLogo.value = null
  const input = evento.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  if (!LOGO_TIPOS.includes(file.type)) {
    erroLogo.value = t('configuracoes.logotipoTipo')
    return
  }
  if (file.size > LOGO_MAX) {
    erroLogo.value = t('configuracoes.logotipoGrande')
    return
  }
  try {
    const data_url = await lerComoDataUrl(file)
    const resultado = ou(
      await api.PUT('/api/v1/admin/settings/logo', { body: { data_url } }),
      t('comum.erroInesperado'),
    )
    branding.aplicar(resultado)
    toast.show({ title: t('configuracoes.logotipoSalvo') })
  } catch (e) {
    erroLogo.value = (e as Error).message
  }
}

async function removerLogo() {
  erroLogo.value = null
  try {
    branding.aplicar(ou(await api.DELETE('/api/v1/admin/settings/logo'), t('comum.erroInesperado')))
    toast.show({ title: t('configuracoes.logotipoRemovido') })
  } catch (e) {
    erroLogo.value = (e as Error).message
  }
}
</script>

<template>
  <div class="mx-auto flex max-w-4xl flex-col gap-6">
    <div>
      <h1 class="text-xl font-semibold">{{ t('configuracoes.titulo') }}</h1>
      <p class="mt-1 text-muted">{{ t('configuracoes.descricao') }}</p>
    </div>

    <form
      class="flex flex-col gap-6 rounded-lg border border-border bg-surface p-4 md:p-6"
      novalidate
      @submit.prevent="salvar"
    >
      <p v-if="erro" class="rounded-md bg-red-bg p-3 text-red-fg" role="alert">{{ erro }}</p>

      <div class="flex max-w-sm flex-col gap-1">
        <SelectField
          v-model="idioma"
          :label="t('configuracoes.idiomaPadrao')"
          :options="opcoesIdioma"
        />
        <p class="text-muted">{{ t('configuracoes.idiomaDica') }}</p>
      </div>

      <section class="flex flex-col gap-4" aria-labelledby="cores-titulo">
        <div>
          <h2 id="cores-titulo" class="font-semibold">{{ t('configuracoes.cores') }}</h2>
          <p class="mt-1 text-muted">{{ t('configuracoes.coresDescricao') }}</p>
        </div>
        <div class="flex flex-col gap-2" role="group" aria-labelledby="predefinidas-titulo">
          <p id="predefinidas-titulo" class="font-medium">
            {{ t('configuracoes.predefinidas') }}
          </p>
          <p class="text-muted">{{ t('configuracoes.predefinidasDica') }}</p>
          <div class="flex flex-wrap gap-2">
            <button
              v-for="p in PREDEFINIDAS"
              :key="p.id"
              type="button"
              :aria-pressed="iguais(p.cores)"
              class="inline-flex items-center gap-2 rounded-md border border-border-input bg-surface px-3 py-2 text-fg hover:bg-surface-raised aria-pressed:border-primary aria-pressed:bg-primary-subtle aria-pressed:font-semibold"
              @click="usarPredefinida(p.cores)"
            >
              <span class="flex" aria-hidden="true">
                <span
                  v-for="(cor, i) in [p.cores.brand, p.cores.neutral, p.cores.background]"
                  :key="i"
                  class="-ml-1 size-5 rounded-full border border-border-input first:ml-0"
                  :style="{ backgroundColor: cor }"
                />
              </span>
              {{ t(`configuracoes.predefinida.${p.id}`) }}
            </button>
          </div>
        </div>
        <div class="grid gap-4 md:grid-cols-3">
          <div v-for="campo in CAMPOS" :key="campo.chave" class="flex flex-col gap-1">
            <label :for="`cor-${campo.chave}`" class="font-medium">{{ t(campo.rotulo) }}</label>
            <div class="flex items-center gap-2">
              <input
                v-model="cores[campo.chave]"
                type="color"
                :aria-label="t(campo.rotulo)"
                class="h-10 w-12 shrink-0 cursor-pointer rounded-md border border-border-input bg-surface p-1"
              />
              <input
                :id="`cor-${campo.chave}`"
                v-model.trim="cores[campo.chave]"
                type="text"
                maxlength="7"
                spellcheck="false"
                :aria-invalid="HEX.test(cores[campo.chave]) ? undefined : true"
                :aria-describedby="`cor-${campo.chave}-dica`"
                class="h-10 w-full rounded-md border border-border-input bg-surface px-3 font-mono text-fg uppercase"
              />
            </div>
            <p :id="`cor-${campo.chave}-dica`" class="text-muted">
              {{ HEX.test(cores[campo.chave]) ? t(campo.dica) : t('configuracoes.hexInvalido') }}
            </p>
          </div>
        </div>
        <p v-if="corAjustada" class="text-muted">
          {{ t('configuracoes.ajustada', { cor: corAjustada }) }}
        </p>

        <div class="grid gap-4 md:grid-cols-2" :aria-label="t('configuracoes.previa')" role="group">
          <div
            v-for="modo in ['claro', 'escuro'] as const"
            :key="modo"
            :class="[
              'rounded-lg border border-border bg-bg p-4 text-fg',
              modo === 'escuro' && 'dark',
            ]"
            :style="variaveis(previa[modo])"
          >
            <p class="mb-3 text-xs font-semibold text-muted uppercase">
              {{ t(modo === 'claro' ? 'configuracoes.previaClaro' : 'configuracoes.previaEscuro') }}
            </p>
            <div class="flex flex-col gap-3 rounded-lg border border-border bg-surface p-4">
              <AppLogo />
              <span
                class="inline-flex w-fit rounded-md bg-primary-subtle px-3 py-1.5 font-medium text-primary"
              >
                {{ t('menu.chamados') }}
              </span>
              <p class="font-semibold">#1234 {{ t('configuracoes.previaTitulo') }}</p>
              <p class="text-muted">{{ t('configuracoes.previaTexto') }}</p>
              <a href="#" class="w-fit text-primary underline" @click.prevent>{{
                t('configuracoes.previaLink')
              }}</a>
              <input
                type="text"
                :placeholder="t('configuracoes.previaCampo')"
                tabindex="-1"
                class="h-10 rounded-md border border-border-input bg-surface px-3 text-fg placeholder:text-muted"
              />
              <div class="flex flex-wrap gap-2">
                <Button tabindex="-1">{{ t('configuracoes.previaBotao') }}</Button>
                <Button variant="secondary" tabindex="-1">{{
                  t('configuracoes.previaSecundario')
                }}</Button>
              </div>
              <div class="rounded-md bg-surface-raised p-2 text-muted">
                {{ t('comum.carregando') }}
              </div>
            </div>
          </div>
        </div>
      </section>

      <div class="flex justify-end border-t border-border pt-4">
        <Button type="submit" :disabled="salvando || !validas">{{
          t('configuracoes.salvar')
        }}</Button>
      </div>
    </form>

    <section
      class="flex flex-col gap-3 rounded-lg border border-border bg-surface p-4 md:p-6"
      aria-labelledby="logotipo-titulo"
    >
      <div>
        <h2 id="logotipo-titulo" class="font-semibold">{{ t('configuracoes.logotipo') }}</h2>
        <p class="mt-1 text-muted">{{ t('configuracoes.logotipoDescricao') }}</p>
      </div>
      <p v-if="erroLogo" class="rounded-md bg-red-bg p-3 text-red-fg" role="alert">
        {{ erroLogo }}
      </p>
      <div class="flex flex-wrap items-center gap-4">
        <div class="rounded-md border border-border p-3"><AppLogo /></div>
        <p v-if="!branding.dados?.logo_url" class="text-muted">
          {{ t('configuracoes.semLogotipo') }}
        </p>
      </div>
      <div class="flex flex-wrap gap-2">
        <input
          ref="arquivo"
          type="file"
          :accept="LOGO_TIPOS.join(',')"
          class="sr-only"
          tabindex="-1"
          :aria-label="t('configuracoes.enviarLogotipo')"
          @change="enviarLogo"
        />
        <Button variant="secondary" @click="arquivo?.click()">{{
          t('configuracoes.enviarLogotipo')
        }}</Button>
        <Button v-if="branding.dados?.logo_url" variant="ghost" @click="removerLogo">
          {{ t('configuracoes.removerLogotipo') }}
        </Button>
      </div>
    </section>
  </div>
</template>
