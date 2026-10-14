<script setup lang="ts">
withDefaults(
  defineProps<{
    variant?: 'primary' | 'secondary' | 'danger' | 'ghost' | 'gold'
    size?: 'sm' | 'md'
    type?: 'button' | 'submit' | 'reset'
    disabled?: boolean
  }>(),
  { variant: 'primary', size: 'md', type: 'button', disabled: false },
)

const variants = {
  primary: 'bg-primary text-on-primary hover:bg-primary-hover',
  secondary: 'border border-border-input bg-surface text-fg hover:bg-surface-raised',
  danger: 'bg-danger text-on-danger hover:opacity-90',
  ghost: 'text-fg hover:bg-surface-raised',
  gold: 'bg-gold text-on-gold hover:bg-gold-hover',
}
const sizes = { sm: 'h-8 px-3 text-sm', md: 'h-10 px-4 text-sm' }
</script>

<template>
  <button
    :type="type"
    :disabled="disabled"
    :class="[
      'inline-flex items-center justify-center gap-2 rounded-md font-medium transition-colors',
      'disabled:cursor-not-allowed disabled:opacity-50',
      variants[variant],
      sizes[size],
    ]"
  >
    <slot />
  </button>
</template>
