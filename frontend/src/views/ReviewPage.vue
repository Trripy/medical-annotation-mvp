<script setup lang="ts">
import { DataAnalysis } from '@element-plus/icons-vue'
import { useI18n } from 'vue-i18n'

import AppSidebar from '../components/AppSidebar.vue'

const { t } = useI18n()
</script>

<template>
  <main class="workspace">
    <AppSidebar :subtitle="t('review.title')" />

    <section class="content">
      <header class="topbar">
        <div>
          <p class="eyebrow">{{ t('review.qualityControl') }}</p>
          <h2>{{ t('review.title') }}</h2>
        </div>
      </header>

      <section class="placeholder-panel action-panel">
        <el-icon><DataAnalysis /></el-icon>
        <p>{{ t('review.placeholder') }}</p>
      </section>
    </section>
  </main>
</template>
