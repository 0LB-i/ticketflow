import { useQuery } from '@tanstack/vue-query'

import { api, ou } from '@/api/client'

/** Os status na ordem definida em Configurações. */
export function useStatus() {
  return useQuery({
    queryKey: ['status'],
    queryFn: async () => ou(await api.GET('/api/v1/statuses')).items,
    staleTime: Infinity,
  })
}
