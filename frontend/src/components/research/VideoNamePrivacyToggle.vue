<script setup lang="ts">
import { Hide, View } from '@element-plus/icons-vue'
import { storeToRefs } from 'pinia'
import { useI18n } from 'vue-i18n'

import { usePrivacyStore } from '../../stores/privacy'

defineProps<{
  compact?: boolean
}>()

const { t } = useI18n()
const privacyStore = usePrivacyStore()
const { hideResearchVideoNames } = storeToRefs(privacyStore)
</script>

<template>
  <el-tooltip :content="t('privacy.videoNames.description')" placement="bottom">
    <el-button
      class="video-name-privacy-toggle"
      :class="{ 'is-active': hideResearchVideoNames, compact }"
      :aria-label="hideResearchVideoNames ? t('privacy.videoNames.hidden') : t('privacy.videoNames.hide')"
      :type="hideResearchVideoNames ? 'warning' : 'default'"
      :plain="!hideResearchVideoNames"
      @click="privacyStore.toggleResearchVideoNames()"
    >
      <el-icon><Hide v-if="hideResearchVideoNames" /><View v-else /></el-icon>
      <span v-if="!compact">{{ hideResearchVideoNames ? t('privacy.videoNames.hidden') : t('privacy.videoNames.hide') }}</span>
    </el-button>
  </el-tooltip>
</template>

<style scoped>
.video-name-privacy-toggle {
  white-space: nowrap;
}

.video-name-privacy-toggle.compact {
  padding-inline: 0.58rem;
}
</style>
