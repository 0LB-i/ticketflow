<script setup lang="ts">
/** Logotipo provisório (docs/17 §17.6): quadrado laranja com "T" + nome do sistema. */
</script>

<template>
  <span class="inline-flex items-center gap-2 text-base font-bold text-fg">
    <svg viewBox="0 0 32 32" class="size-7 shrink-0" aria-hidden="true">
      <rect width="32" height="32" rx="7" fill="var(--tf-brand)" />
      <path d="M9 9h14v4h-5v12h-4V13H9z" fill="#fff" />
    </svg>
    {{ $t('app.nome') }}
  </span>
</template>
