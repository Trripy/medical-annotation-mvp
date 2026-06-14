<script setup lang="ts">
import { Connection } from '@element-plus/icons-vue'
import { storeToRefs } from 'pinia'
import { onMounted } from 'vue'

import AppSidebar from '../components/AppSidebar.vue'
import { usePlatformStore } from '../stores/platform'

const platformStore = usePlatformStore()
const { health, loading, error } = storeToRefs(platformStore)

onMounted(() => {
  void platformStore.fetchHealth()
})
</script>

<template>
  <main class="workspace">
    <AppSidebar />

    <section class="content">
      <header class="topbar">
        <div>
          <p class="eyebrow">Local filesystem first</p>
          <h2>医学图像标注平台骨架</h2>
        </div>
        <el-button :loading="loading" type="primary" @click="platformStore.fetchHealth">
          <el-icon><Connection /></el-icon>
          Check API
        </el-button>
      </header>

      <div class="status-grid">
        <el-card shadow="never">
          <template #header>Backend</template>
          <el-tag :type="health?.status === 'ok' ? 'success' : 'info'">
            {{ health?.status ?? 'pending' }}
          </el-tag>
        </el-card>

        <el-card shadow="never">
          <template #header>PostgreSQL</template>
          <el-tag :type="health?.database === 'ok' ? 'success' : 'info'">
            {{ health?.database ?? 'pending' }}
          </el-tag>
        </el-card>

        <el-card shadow="never">
          <template #header>Storage</template>
          <el-tag :type="health?.storage_ready ? 'success' : 'info'">
            {{ health?.storage_ready ? 'ready' : 'pending' }}
          </el-tag>
        </el-card>
      </div>

      <el-alert v-if="error" :title="error" type="error" show-icon />

      <section class="canvas-shell">
        <div class="canvas-toolbar">
          <el-button disabled>Upload Study</el-button>
          <el-button disabled>Open Viewer</el-button>
          <el-button disabled>Export Labels</el-button>
        </div>
        <div class="viewer-placeholder">
          <div class="scan-frame">
            <span></span>
            <span></span>
            <span></span>
          </div>
          <p>基础项目已就绪，后续可接入 DICOM/NIfTI 浏览、标注任务和标签导出。</p>
          <small v-if="health">Storage root: {{ health.storage_root }}</small>
        </div>
      </section>
    </section>
  </main>
</template>
