<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import { useVideoPlaybackRate } from '../composables/useVideoPlaybackRate.ts'
import {
  formatPlaybackRateLabel,
  VIDEO_PLAYBACK_RATE_OPTIONS,
  type VideoPlaybackRate,
} from '../utils/videoPlaybackRate.ts'

defineProps<{
  compact?: boolean
}>()

const { t } = useI18n()
const { playbackRate, setPlaybackRate } = useVideoPlaybackRate()

const selectedRate = computed({
  get: () => playbackRate.value,
  set: (value: VideoPlaybackRate) => setPlaybackRate(value),
})

function optionLabel(rate: VideoPlaybackRate) {
  const label = formatPlaybackRateLabel(rate)
  return rate === 1 ? `${label} (${t('video.normalSpeed')})` : label
}
</script>

<template>
  <label class="video-playback-rate-control" :class="{ compact }">
    <span v-if="!compact" class="video-playback-rate-label">{{ t('video.playbackSpeed') }}</span>
    <el-select
      v-model="selectedRate"
      class="video-playback-rate-select"
      size="small"
      :aria-label="t('accessibility.changePlaybackSpeed')"
      :teleported="false"
    >
      <el-option
        v-for="rate in VIDEO_PLAYBACK_RATE_OPTIONS"
        :key="rate"
        :label="optionLabel(rate)"
        :value="rate"
      />
    </el-select>
  </label>
</template>
