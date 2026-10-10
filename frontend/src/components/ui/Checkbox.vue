<script setup lang="ts">
defineProps<{ label: string }>()
const model = defineModel<boolean>({ default: false })
</script>

<template>
  <label class="inline-flex cursor-pointer items-center gap-2">
    <input v-model="model" type="checkbox" class="size-4 accent-(--tf-primary)" />
    {{ label }}
  </label>
</template>
