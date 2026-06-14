<script setup lang="ts">
import { DataAnalysis } from '@element-plus/icons-vue'

import AppSidebar from '../components/AppSidebar.vue'
</script>

<template>
  <main class="workspace">
    <AppSidebar subtitle="Review" />

    <section class="content">
      <header class="topbar">
        <div>
          <p class="eyebrow">Quality control</p>
          <h2>Review</h2>
        </div>
      </header>

      <section class="placeholder-panel action-panel">
        <el-icon><DataAnalysis /></el-icon>
        <p>Review queues and approval workflows are not implemented in this MVP yet.</p>
      </section>
    </section>
  </main>
</template>
