import { useQuery } from '@tanstack/vue-query'

import { api } from '@/api/client'

export function useHealth() {
  return useQuery({
    queryKey: ['health'],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/health')
      if (error || !data) throw new Error('health')
      return data
    },
    retry: false,
  })
}
