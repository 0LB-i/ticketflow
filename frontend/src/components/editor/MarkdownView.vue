<script setup lang="ts">
import { computed } from 'vue'

import { renderizarMarkdown } from './markdown'

const props = defineProps<{ source: string }>()
const html = computed(() => renderizarMarkdown(props.source))
</script>

<template>
  <!-- eslint-disable-next-line vue/no-v-html -- HTML gerado com html: false (markdown.ts) -->
  <div class="texto-formatado" v-html="html" />
</template>
