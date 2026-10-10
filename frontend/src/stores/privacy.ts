import { defineStore } from 'pinia'

export const RESEARCH_VIDEO_NAME_PRIVACY_STORAGE_KEY = 'medicalAnnotation.hideResearchVideoNames'

function readStoredBoolean(storage: Pick<Storage, 'getItem'> | null | undefined, key: string): boolean {
  if (!storage) return false
  return storage.getItem(key) === 'true'
}

function writeStoredBoolean(storage: Pick<Storage, 'setItem'> | null | undefined, key: string, value: boolean): void {
  if (!storage) return
  storage.setItem(key, String(value))
}

export const usePrivacyStore = defineStore('privacy', {
  state: () => ({
    hideResearchVideoNames: readStoredBoolean(
      typeof window === 'undefined' ? null : window.localStorage,
      RESEARCH_VIDEO_NAME_PRIVACY_STORAGE_KEY,
    ),
  }),
  actions: {
    setHideResearchVideoNames(value: boolean) {
      this.hideResearchVideoNames = value
      writeStoredBoolean(
        typeof window === 'undefined' ? null : window.localStorage,
        RESEARCH_VIDEO_NAME_PRIVACY_STORAGE_KEY,
        value,
      )
    },
    toggleResearchVideoNames() {
      this.setHideResearchVideoNames(!this.hideResearchVideoNames)
    },
  },
})

