<script setup lang="ts">
import { Tickets, UploadFilled } from '@element-plus/icons-vue'

import AppSidebar from '../components/AppSidebar.vue'
</script>

<template>
  <main class="workspace">
    <AppSidebar subtitle="Annotation" />

    <section class="content">
      <header class="topbar">
        <div>
          <p class="eyebrow">Task entry</p>
          <h2>Annotation</h2>
        </div>
        <router-link to="/jobs">
          <el-button type="primary">
            <el-icon><Tickets /></el-icon>
            Open Jobs
          </el-button>
        </router-link>
      </header>

      <section class="placeholder-panel action-panel">
        <el-icon><UploadFilled /></el-icon>
        <p>Upload flow is available through the backend API. After uploading task data, open Jobs to start annotation.</p>
      </section>
    </section>
  </main>
</template>
