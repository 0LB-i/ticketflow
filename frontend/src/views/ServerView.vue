<script setup lang="ts">
import { useRoute } from 'vue-router'

/**
 * Tela que já migrou para o servidor (Jinja2, ADR 0011): recarrega a página para o uvicorn
 * respondê-la. Some junto com a SPA, na troca final.
 */
window.location.replace(useRoute().fullPath)
</script>

<template>
  <div />
</template>
