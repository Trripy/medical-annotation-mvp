import { createI18n } from 'vue-i18n'

import { LOCALE_STORAGE_KEY, persistLocale, readPersistedLocale, type SupportedLocale } from '../utils/locale.ts'
import enUS from './locales/en-US.ts'
import zhCN from './locales/zh-CN.ts'

export const messages = {
  'en-US': enUS,
  'zh-CN': zhCN,
} as const

export const fallbackLocale: SupportedLocale = 'en-US'

export const initialLocale = readPersistedLocale(
  typeof window === 'undefined' ? null : window.localStorage,
  typeof navigator === 'undefined' ? undefined : navigator.language,
)

persistLocale(initialLocale, typeof window === 'undefined' ? null : window.localStorage)

export const i18n = createI18n({
  legacy: false,
  locale: initialLocale,
  fallbackLocale,
  messages,
  missingWarn: false,
  fallbackWarn: false,
})

export function setLocale(locale: SupportedLocale): void {
  i18n.global.locale.value = locale
  persistLocale(locale, typeof window === 'undefined' ? null : window.localStorage)
}

export { LOCALE_STORAGE_KEY }
