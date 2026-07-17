<script setup lang="ts">
import { VideoPlay } from '@element-plus/icons-vue'

import AppSidebar from '../components/AppSidebar.vue'
</script>

<template>
  <main class="workspace">
    <AppSidebar subtitle="Research" />

    <section class="content">
      <header class="topbar">
        <div>
          <p class="eyebrow">Experimental workspace</p>
          <h2>Research</h2>
          <p class="page-subtitle">Research features are isolated from production annotation projects.</p>
        </div>
      </header>

      <section class="research-grid">
        <article class="research-card">
          <div class="research-card-icon">
            <el-icon><VideoPlay /></el-icon>
          </div>
          <div class="research-card-content">
            <h3>Video Annotation Experiments</h3>
            <p>Import videos, play them frame by frame, and reuse the existing annotation tools on individual frames.</p>
          </div>
          <router-link to="/research/videos" class="research-card-link">
            <el-button type="primary">Open</el-button>
          </router-link>
        </article>
      </section>
    </section>
  </main>
</template>
