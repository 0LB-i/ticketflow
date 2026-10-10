import skipFormatting from '@vue/eslint-config-prettier/skip-formatting'
import { defineConfigWithVueTs, vueTsConfigs } from '@vue/eslint-config-typescript'
import pluginVue from 'eslint-plugin-vue'

export default defineConfigWithVueTs(
  { ignores: ['dist/**', 'public/**', 'src/api/schema.d.ts', 'src/api/openapi.json'] },
  pluginVue.configs['flat/recommended'],
  vueTsConfigs.recommended,
  {
    rules: {
      // Componentes de base têm nomes de uma palavra (Button, Modal), prefixados no uso.
      'vue/multi-word-component-names': 'off',
    },
  },
  skipFormatting,
)
