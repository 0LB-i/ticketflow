<script setup lang="ts">
import AppLayout from '@/components/layout/AppLayout.vue'
import ToastHost from '@/components/ui/ToastHost.vue'
import { useThemeStore } from '@/stores/theme'

useThemeStore()
</script>

<template>
  <AppLayout>
    <RouterView />
  </AppLayout>
  <ToastHost />
</template>
