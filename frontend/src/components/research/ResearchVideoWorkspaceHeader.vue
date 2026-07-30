<script setup lang="ts">
import { Back } from '@element-plus/icons-vue'
import { useI18n } from 'vue-i18n'

import ResearchVideoTaskNav from './ResearchVideoTaskNav.vue'
import type { ResearchTaskKey } from '../../utils/researchWorkflowUi.ts'

defineProps<{
  activeTask: ResearchTaskKey
  currentFrameIndex: number
  metaItems: string[]
  taskLabel: string
  title: string
  videoId: number | string
}>()

const { t } = useI18n()
</script>

<template>
  <header class="research-workspace-header">
    <div class="research-workspace-header-top">
      <router-link class="research-workspace-breadcrumb" to="/research/videos">
        <el-icon><Back /></el-icon>
        <span>{{ t('phaseAnnotation.researchVideos') }}</span>
      </router-link>
      <span class="research-workspace-breadcrumb-separator">·</span>
      <span class="research-workspace-task-pill">{{ taskLabel }}</span>

      <h1 class="research-workspace-title" :title="title">
        {{ title }}
      </h1>

      <ResearchVideoTaskNav
        class="research-workspace-task-nav"
        :active-task="activeTask"
        :current-frame-index="currentFrameIndex"
        :video-id="videoId"
      />
    </div>

    <div class="research-workspace-meta" :aria-label="t('accessibility.videoWorkspaceStatus')">
      <span
        v-for="item in metaItems.filter(Boolean)"
        :key="item"
      >
        {{ item }}
      </span>
    </div>
  </header>
</template>

<style scoped>
.research-workspace-header {
  display: flex;
  flex: 0 0 auto;
  flex-direction: column;
  gap: 0.25rem;
  min-width: 0;
  padding: 0.5rem 1rem;
  border-bottom: 1px solid rgba(148, 163, 184, 0.14);
  background: rgba(15, 23, 42, 0.9);
  color: #e2e8f0;
}

.research-workspace-header-top {
  display: grid;
  grid-template-columns: auto auto auto minmax(0, 1fr) auto;
  gap: 0.45rem;
  align-items: center;
  min-width: 0;
}

.research-workspace-breadcrumb {
  display: inline-flex;
  align-items: center;
  gap: 0.32rem;
  color: #bae6fd;
  text-decoration: none;
  font-size: 0.86rem;
  white-space: nowrap;
}

.research-workspace-breadcrumb-separator {
  color: rgba(148, 163, 184, 0.82);
}

.research-workspace-task-pill {
  padding: 0.18rem 0.45rem;
  border-radius: 999px;
  background: rgba(8, 47, 73, 0.74);
  color: #cffafe;
  font-size: 0.82rem;
  font-weight: 700;
  white-space: nowrap;
}

.research-workspace-title {
  min-width: 0;
  margin: 0;
  overflow: hidden;
  color: #f8fafc;
  font-size: clamp(1.25rem, 1.6vw, 1.75rem);
  font-weight: 800;
  line-height: 1.15;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.research-workspace-task-nav {
  justify-self: end;
}

.research-workspace-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem 0.7rem;
  min-width: 0;
  padding-left: min(9rem, 16vw);
  color: rgba(148, 163, 184, 0.94);
  font-size: 0.84rem;
  line-height: 1.25;
}

.research-workspace-meta span + span::before {
  content: '·';
  margin-right: 0.7rem;
  color: rgba(100, 116, 139, 0.95);
}

@media (max-width: 1279px) {
  .research-workspace-header-top {
    grid-template-columns: auto auto auto minmax(0, 1fr);
  }

  .research-workspace-task-nav {
    grid-column: 1 / -1;
    justify-self: end;
  }

  .research-workspace-meta {
    padding-left: 0;
  }
}

@media (max-width: 899px) {
  .research-workspace-header {
    padding: 0.45rem 0.75rem;
  }

  .research-workspace-header-top {
    grid-template-columns: auto auto auto minmax(0, 1fr);
  }

  .research-workspace-title {
    grid-column: 1 / -1;
    font-size: 1.12rem;
  }

  .research-workspace-task-nav {
    justify-self: start;
  }
}
</style>
