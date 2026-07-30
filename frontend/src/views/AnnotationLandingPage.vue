<script setup lang="ts">
import { Tickets, UploadFilled } from '@element-plus/icons-vue'
import { useI18n } from 'vue-i18n'

import AppSidebar from '../components/AppSidebar.vue'

const { t } = useI18n()
</script>

<template>
  <main class="workspace">
    <AppSidebar :subtitle="t('landing.subtitle')" />

    <section class="content">
      <header class="topbar">
        <div>
          <p class="eyebrow">{{ t('landing.eyebrow') }}</p>
          <h2>{{ t('landing.title') }}</h2>
        </div>
        <router-link to="/jobs">
          <el-button type="primary">
            <el-icon><Tickets /></el-icon>
            {{ t('landing.openJobs') }}
          </el-button>
        </router-link>
      </header>

      <section class="placeholder-panel action-panel">
        <el-icon><UploadFilled /></el-icon>
        <p>{{ t('landing.placeholder') }}</p>
      </section>
    </section>
  </main>
</template>
