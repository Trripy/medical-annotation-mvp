import { defineStore } from 'pinia'

const ADMIN_STORAGE_KEY = 'isAdmin'
// TODO: Move admin authentication to backend before production.
const ADMIN_PASSWORD = 'zhangyuzhu'

function readStoredAdminState(): boolean {
  if (typeof window === 'undefined') {
    return false
  }

  return window.localStorage.getItem(ADMIN_STORAGE_KEY) === 'true'
}

export const useAdminStore = defineStore('admin', {
  state: () => ({
    isAdmin: readStoredAdminState(),
  }),
  actions: {
    login(password: string) {
      if (password !== ADMIN_PASSWORD) {
        return false
      }

      this.isAdmin = true
      window.localStorage.setItem(ADMIN_STORAGE_KEY, 'true')
      return true
    },
    exit() {
      this.isAdmin = false
      window.localStorage.removeItem(ADMIN_STORAGE_KEY)
    },
  },
})
