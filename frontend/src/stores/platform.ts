import { defineStore } from 'pinia'

import { apiV1Url } from '../utils/api'

type HealthStatus = {
  status: string
  database: string
  storage_root: string
  storage_ready: boolean
}

export const usePlatformStore = defineStore('platform', {
  state: () => ({
    health: null as HealthStatus | null,
    loading: false,
    error: '',
  }),
  actions: {
    async fetchHealth() {
      this.loading = true
      this.error = ''

      try {
        const response = await fetch(apiV1Url('/health'))

        if (!response.ok) {
          throw new Error(`Health check failed: ${response.status}`)
        }

        this.health = await response.json()
      } catch (error) {
        this.error = error instanceof Error ? error.message : 'Unknown error'
      } finally {
        this.loading = false
      }
    },
  },
})
