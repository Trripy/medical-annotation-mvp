<script setup lang="ts">
import { watchEffect } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'

const route = useRoute()
const { t } = useI18n()

watchEffect(() => {
  if (typeof document === 'undefined') {
    return
  }

  const path = route.path
  if (path.includes('/phases')) {
    document.title = `${t('phaseAnnotation.title')} | ${t('common.appName')}`
  } else if (path.includes('/skills')) {
    document.title = `${t('skillAssessment.title')} | ${t('common.appName')}`
  } else if (path.includes('/annotate')) {
    document.title = `${t('frameAnnotation.title')} | ${t('common.appName')}`
  } else if (path.startsWith('/research')) {
    document.title = `${t('research.title')} | ${t('common.appName')}`
  } else {
    document.title = t('common.appName')
  }
})
</script>

<template>
  <router-view />
</template>
