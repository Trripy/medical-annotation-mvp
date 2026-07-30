<script setup lang="ts">
import { Connection } from '@element-plus/icons-vue'
import { storeToRefs } from 'pinia'
import { onMounted } from 'vue'
import { useI18n } from 'vue-i18n'

import AppSidebar from '../components/AppSidebar.vue'
import { usePlatformStore } from '../stores/platform'

const { t } = useI18n()
const platformStore = usePlatformStore()
const { health, loading, error } = storeToRefs(platformStore)

onMounted(() => {
  void platformStore.fetchHealth()
})

function formatHealthStatus(status: string | null | undefined) {
  if (status === 'ok') {
    return t('workbench.ready')
  }
  return status ?? t('workbench.pending')
}
</script>

<template>
  <main class="workspace">
    <AppSidebar />

    <section class="content">
      <header class="topbar">
        <div>
          <p class="eyebrow">{{ t('workbench.eyebrow') }}</p>
          <h2>{{ t('workbench.title') }}</h2>
        </div>
        <el-button :loading="loading" type="primary" @click="platformStore.fetchHealth">
          <el-icon><Connection /></el-icon>
          {{ t('workbench.checkApi') }}
        </el-button>
      </header>

      <div class="status-grid">
        <el-card shadow="never">
          <template #header>{{ t('workbench.backend') }}</template>
          <el-tag :type="health?.status === 'ok' ? 'success' : 'info'">
            {{ formatHealthStatus(health?.status) }}
          </el-tag>
        </el-card>

        <el-card shadow="never">
          <template #header>{{ t('workbench.database') }}</template>
          <el-tag :type="health?.database === 'ok' ? 'success' : 'info'">
            {{ formatHealthStatus(health?.database) }}
          </el-tag>
        </el-card>

        <el-card shadow="never">
          <template #header>{{ t('workbench.storage') }}</template>
          <el-tag :type="health?.storage_ready ? 'success' : 'info'">
            {{ health?.storage_ready ? t('workbench.ready') : t('workbench.pending') }}
          </el-tag>
        </el-card>
      </div>

      <el-alert v-if="error" :title="error" type="error" show-icon />

      <section class="canvas-shell">
        <div class="canvas-toolbar">
          <el-button disabled>{{ t('workbench.uploadStudy') }}</el-button>
          <el-button disabled>{{ t('workbench.openViewer') }}</el-button>
          <el-button disabled>{{ t('workbench.exportLabels') }}</el-button>
        </div>
        <div class="viewer-placeholder">
          <div class="scan-frame">
            <span></span>
            <span></span>
            <span></span>
          </div>
          <p>{{ t('workbench.placeholder') }}</p>
          <small v-if="health">{{ t('workbench.storageRoot', { path: health.storage_root }) }}</small>
        </div>
      </section>
    </section>
  </main>
</template>
