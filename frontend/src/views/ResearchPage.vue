<script setup lang="ts">
import { VideoPlay } from '@element-plus/icons-vue'
import { useI18n } from 'vue-i18n'

import AppSidebar from '../components/AppSidebar.vue'

const { t } = useI18n()
</script>

<template>
  <main class="workspace">
    <AppSidebar :subtitle="t('research.subtitle')" />

    <section class="content">
      <header class="topbar">
        <div>
          <p class="eyebrow">{{ t('research.experimentalWorkspace') }}</p>
          <h2>{{ t('research.title') }}</h2>
          <p class="page-subtitle">{{ t('research.description') }}</p>
        </div>
      </header>

      <section class="research-grid">
        <article class="research-card">
          <div class="research-card-icon">
            <el-icon><VideoPlay /></el-icon>
          </div>
          <div class="research-card-content">
            <h3>{{ t('research.videoExperiments') }}</h3>
            <p>{{ t('research.videoExperimentsDescription') }}</p>
          </div>
          <router-link to="/research/videos" class="research-card-link">
            <el-button type="primary">{{ t('common.open') }}</el-button>
          </router-link>
        </article>
      </section>
    </section>
  </main>
</template>
