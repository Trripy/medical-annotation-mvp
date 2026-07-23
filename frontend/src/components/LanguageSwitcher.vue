<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'

import { setLocale } from '../i18n'
import {
  applyLocaleFromStorageEvent,
  isSupportedLocale,
  SUPPORTED_LOCALES,
  type SupportedLocale,
} from '../utils/locale'

defineProps<{
  compact?: boolean
}>()

const { locale, t } = useI18n()

const currentLocale = computed({
  get: () => (isSupportedLocale(locale.value) ? locale.value : 'en-US'),
  set: (value: SupportedLocale) => {
    if (value !== locale.value) {
      setLocale(value)
    }
  },
})

function handleStorage(event: StorageEvent) {
  applyLocaleFromStorageEvent(event, (nextLocale) => {
    locale.value = nextLocale
    document.documentElement.lang = nextLocale
  })
}

onMounted(() => {
  window.addEventListener('storage', handleStorage)
})

onBeforeUnmount(() => {
  window.removeEventListener('storage', handleStorage)
})
</script>

<template>
  <label class="language-switcher" :class="{ compact }">
    <span v-if="!compact" class="language-switcher-label">{{ t('common.language') }}</span>
    <el-select
      v-model="currentLocale"
      class="language-switcher-select"
      size="small"
      :aria-label="t('common.selectLanguage')"
      :teleported="false"
    >
      <el-option
        v-for="option in SUPPORTED_LOCALES"
        :key="option"
        :label="option === 'zh-CN' ? `🌐 ${t('common.chinese')}` : `🌐 ${t('common.english')}`"
        :value="option"
      />
    </el-select>
  </label>
</template>
