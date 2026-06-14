import { defineStore } from 'pinia'

import { apiUrl } from '../utils/api'

export type UserAccount = {
  id: number
  username: string
}

const USERNAME_STORAGE_KEY = 'currentUsername'
// TODO: Replace username-only login with real authentication before production.

function readStoredUsername(): string {
  if (typeof window === 'undefined') {
    return ''
  }

  return window.localStorage.getItem(USERNAME_STORAGE_KEY) ?? ''
}

async function readErrorMessage(response: Response, fallback: string): Promise<string> {
  try {
    const payload = await response.json()
    return typeof payload.detail === 'string' ? payload.detail : fallback
  } catch {
    return fallback
  }
}

export const useUsersStore = defineStore('users', {
  state: () => ({
    currentUsername: readStoredUsername(),
    users: [] as UserAccount[],
    loading: false,
    error: '',
  }),
  actions: {
    async login(username: string) {
      const normalizedUsername = username.trim()
      if (!normalizedUsername) {
        this.error = 'Username is required'
        return false
      }

      this.loading = true
      this.error = ''

      try {
        const response = await fetch(apiUrl('/api/users/login'), {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ username: normalizedUsername }),
        })

        if (!response.ok) {
          throw new Error(await readErrorMessage(response, 'Login failed'))
        }

        const payload = await response.json() as { username: string }
        this.currentUsername = payload.username
        window.localStorage.setItem(USERNAME_STORAGE_KEY, payload.username)
        return true
      } catch (error) {
        this.error = error instanceof Error ? error.message : 'Unknown error'
        return false
      } finally {
        this.loading = false
      }
    },
    logout() {
      this.currentUsername = ''
      window.localStorage.removeItem(USERNAME_STORAGE_KEY)
    },
    async fetchUsers() {
      this.loading = true
      this.error = ''

      try {
        const response = await fetch(apiUrl('/api/users'))
        if (!response.ok) {
          throw new Error(await readErrorMessage(response, `Users request failed: ${response.status}`))
        }

        this.users = await response.json()
      } catch (error) {
        this.error = error instanceof Error ? error.message : 'Unknown error'
      } finally {
        this.loading = false
      }
    },
    async addUser(username: string) {
      const normalizedUsername = username.trim()
      if (!normalizedUsername) {
        this.error = 'Username is required'
        return false
      }

      this.loading = true
      this.error = ''

      try {
        const response = await fetch(apiUrl('/api/users'), {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ username: normalizedUsername }),
        })

        if (!response.ok) {
          throw new Error(await readErrorMessage(response, `Create user failed: ${response.status}`))
        }

        await this.fetchUsers()
        return true
      } catch (error) {
        this.error = error instanceof Error ? error.message : 'Unknown error'
        return false
      } finally {
        this.loading = false
      }
    },
    async deleteUser(userId: number) {
      this.loading = true
      this.error = ''

      try {
        const response = await fetch(apiUrl(`/api/users/${userId}`), {
          method: 'DELETE',
        })

        if (!response.ok) {
          throw new Error(await readErrorMessage(response, `Delete user failed: ${response.status}`))
        }

        this.users = this.users.filter((user) => user.id !== userId)
        return true
      } catch (error) {
        this.error = error instanceof Error ? error.message : 'Unknown error'
        return false
      } finally {
        this.loading = false
      }
    },
  },
})
