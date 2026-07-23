<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import LanguageSwitcher from '../LanguageSwitcher.vue'

const props = defineProps<{
  activeTask: 'frame' | 'phase' | 'skill'
  currentFrameIndex: number
  videoId: number | string
}>()

const { t } = useI18n()

const sharedQuery = computed(() => (
  props.currentFrameIndex >= 0
    ? { frame: String(props.currentFrameIndex) }
    : {}
))
</script>

<template>
  <div class="research-task-nav-shell">
    <nav class="research-task-nav" :aria-label="t('accessibility.researchTasks')">
      <router-link
        class="research-task-nav-link"
        :class="{ active: activeTask === 'frame' }"
        :to="{ path: `/research/videos/${videoId}/annotate`, query: sharedQuery }"
      >
        {{ t('taskNav.frame') }}
      </router-link>
      <router-link
        class="research-task-nav-link"
        :class="{ active: activeTask === 'phase' }"
        :to="{ path: `/research/videos/${videoId}/phases`, query: sharedQuery }"
      >
        {{ t('taskNav.phase') }}
      </router-link>
      <router-link
        class="research-task-nav-link"
        :class="{ active: activeTask === 'skill' }"
        :to="{ path: `/research/videos/${videoId}/skills`, query: sharedQuery }"
      >
        {{ t('taskNav.skill') }}
      </router-link>
    </nav>
    <LanguageSwitcher compact />
  </div>
</template>

<style scoped>
.research-task-nav-shell {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  min-width: 0;
}

.research-task-nav {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  min-width: 0;
}

.research-task-nav-link {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.7rem 0.95rem;
  border-radius: 999px;
  border: 1px solid rgba(148, 163, 184, 0.24);
  background: rgba(15, 23, 42, 0.68);
  color: rgba(226, 232, 240, 0.9);
  text-decoration: none;
  font-size: 0.92rem;
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
    flex-direction: column;
  }
}
</style>
