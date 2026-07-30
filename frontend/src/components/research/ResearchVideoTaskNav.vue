<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import LanguageSwitcher from '../LanguageSwitcher.vue'
import { buildResearchTaskNavState } from '../../utils/researchWorkflowUi.ts'

const props = defineProps<{
  activeTask: 'frame' | 'phase' | 'skill'
  currentFrameIndex: number
  videoId: number | string
}>()

const { t } = useI18n()

const taskItems = computed(() => buildResearchTaskNavState(props.activeTask, props.currentFrameIndex))

function taskPath(task: 'frame' | 'phase' | 'skill') {
  if (task === 'frame') return `/research/videos/${props.videoId}/annotate`
  if (task === 'phase') return `/research/videos/${props.videoId}/phases`
  return `/research/videos/${props.videoId}/skills`
}

function taskLabel(task: 'frame' | 'phase' | 'skill') {
  if (task === 'frame') return t('taskNav.frame')
  if (task === 'phase') return t('taskNav.phase')
  return t('taskNav.skill')
}
</script>

<template>
  <div class="research-task-nav-shell">
    <nav class="research-task-nav" :aria-label="t('accessibility.researchTasks')">
      <router-link
        v-for="item in taskItems"
        :key="item.task"
        class="research-task-nav-link"
        :class="{ active: item.active }"
        :to="{ path: taskPath(item.task), query: item.query }"
      >
        {{ taskLabel(item.task) }}
      </router-link>
    </nav>
    <LanguageSwitcher compact />
  </div>
</template>

<style scoped>
.research-task-nav-shell {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 0.5rem;
  min-width: 0;
  flex-wrap: wrap;
}

.research-task-nav {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
  min-width: 0;
}

.research-task-nav-link {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.46rem 0.68rem;
  border-radius: 0.52rem;
  border: 1px solid rgba(148, 163, 184, 0.24);
  background: rgba(15, 23, 42, 0.68);
  color: rgba(226, 232, 240, 0.9);
  text-decoration: none;
  font-size: 0.86rem;
  font-weight: 600;
  transition: background-color 140ms ease, border-color 140ms ease, color 140ms ease;
}

.research-task-nav-link:hover:not(.is-disabled),
.research-task-nav-link.active {
  border-color: rgba(34, 211, 238, 0.4);
  background: rgba(8, 47, 73, 0.78);
  color: #ecfeff;
}

.research-task-nav-link.is-disabled {
  cursor: not-allowed;
  opacity: 0.62;
}

.research-task-nav-link span {
  font-size: 0.76rem;
  color: rgba(148, 163, 184, 0.9);
}

@media (max-width: 760px) {
  .research-task-nav-shell {
    align-items: flex-start;
    justify-content: flex-start;
  }

  .research-task-nav-link {
    padding: 0.42rem 0.58rem;
  }
}
</style>
