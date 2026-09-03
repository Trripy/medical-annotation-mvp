<script setup lang="ts">
import { ArrowLeft, VideoPlay } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { storeToRefs } from 'pinia'
import { computed, onBeforeUnmount, onMounted, ref, shallowRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'

import AppSidebar from '../components/AppSidebar.vue'
import VideoPlaybackRateControl from '../components/VideoPlaybackRateControl.vue'
import VideoTrimTimeline from '../components/research/VideoTrimTimeline.vue'
import { useVideoPlaybackRate } from '../composables/useVideoPlaybackRate'
import { useResearchVideosStore, type ResearchVideoTrimInfo } from '../stores/researchVideos'
import {
  backendRangeToUi,
  buildTrimPayload,
  clampTrimRange,
  defaultTrimmedName,
  formatTrimTimestamp,
  frameToSeconds,
  isFullRange,
  isRangeTooShort,
  parseTrimTimestamp,
  readHideSourceAfterTrimPreference,
  sanitizeTrimOutputName,
  secondsToFrame,
  trimOutputFrameCount,
  uiRangeToBackend,
  writeHideSourceAfterTrimPreference,
  type TrimRange,
} from '../utils/videoTrim'

const props = defineProps<{
  videoId: string | number
}>()

const router = useRouter()
const { t } = useI18n()
const store = useResearchVideosStore()
const { loading, saving } = storeToRefs(store)
const videoRef = shallowRef<HTMLVideoElement | null>(null)
const trimInfo = ref<ResearchVideoTrimInfo | null>(null)
const trimRange = ref<TrimRange>({ startFrame: 0, endFrameExclusive: 0 })
const currentFrame = ref(0)
const outputName = ref('')
const acknowledged = ref(false)
const hideSourceAfterSuccess = ref(false)
const rememberHideSourceChoice = ref(false)
const trimResponseId = ref<number | null>(null)
const submitting = ref(false)
const previewing = ref(false)

const sourceVideo = computed(() => trimInfo.value?.video ?? null)
const frameCount = computed(() => sourceVideo.value?.frame_count ?? 0)
const fps = computed(() => sourceVideo.value?.fps ?? 0)
const minimumFrames = computed(() => trimInfo.value?.minimum_keep_frames ?? 10)
const uiRange = computed(() => backendRangeToUi(trimRange.value))
const hasLinkedData = computed(() => {
  const linked = trimInfo.value?.linked_data
  return Boolean(linked && Object.values(linked).some((count) => count > 0))
})
const outputFrames = computed(() => trimOutputFrameCount(trimRange.value))
const outputDurationSeconds = computed(() => frameToSeconds(outputFrames.value, fps.value))
const originalDurationSeconds = computed(() => frameToSeconds(frameCount.value, fps.value))
const removedStartSeconds = computed(() => frameToSeconds(trimRange.value.startFrame, fps.value))
const removedEndSeconds = computed(() => frameToSeconds(frameCount.value - trimRange.value.endFrameExclusive, fps.value))
const startTimeText = computed(() => formatTrimTimestamp(frameToSeconds(trimRange.value.startFrame, fps.value)))
const endTimeText = computed(() => formatTrimTimestamp(frameToSeconds(trimRange.value.endFrameExclusive, fps.value)))
const startFrameInput = computed(() => uiRange.value.startFrameInclusiveOneBased)
const endFrameInput = computed(() => uiRange.value.endFrameInclusiveOneBased)
const submitDisabled = computed(() =>
  saving.value ||
  submitting.value ||
  isFullRange(trimRange.value, frameCount.value) ||
  isRangeTooShort(trimRange.value, minimumFrames.value) ||
  (hasLinkedData.value && !acknowledged.value),
)
const rangeError = computed(() => {
  if (isFullRange(trimRange.value, frameCount.value)) {
    return t('videoTrim.fullRangeUnchanged')
  }
  if (isRangeTooShort(trimRange.value, minimumFrames.value)) {
    return t('videoTrim.rangeTooShort', { count: minimumFrames.value })
  }
  return ''
})

useVideoPlaybackRate(videoRef, computed(() => sourceVideo.value?.file_url ?? null))

onMounted(async () => {
  hideSourceAfterSuccess.value = readHideSourceAfterTrimPreference()
  const videoId = Number(props.videoId)
  const payload = await store.fetchVideoTrimInfo(videoId)
  if (!payload) {
    ElMessage.error(store.error || t('videoTrim.failed'))
    return
  }
  trimInfo.value = payload
  setTrimRange({ startFrame: 0, endFrameExclusive: payload.video.frame_count })
  outputName.value = defaultTrimmedName(payload.video.original_filename || payload.video.name)
})

onBeforeUnmount(() => {
  previewing.value = false
})

function handleTimeUpdate() {
  const video = videoRef.value
  if (!video || !fps.value) {
    return
  }
  currentFrame.value = Math.max(0, Math.min(frameCount.value, Math.floor(video.currentTime * fps.value)))
  if (previewing.value && currentFrame.value >= trimRange.value.endFrameExclusive) {
    video.pause()
    previewing.value = false
    seekToFrame(trimRange.value.endFrameExclusive - 1)
  }
}

function seekToFrame(frame: number) {
  const video = videoRef.value
  if (!video || !fps.value) {
    return
  }
  const clamped = Math.max(0, Math.min(frameCount.value - 1, frame))
  video.currentTime = frameToSeconds(clamped, fps.value)
  currentFrame.value = clamped
}

function setTrimRange(nextRange: TrimRange): TrimRange {
  const next = clampTrimRange(nextRange, frameCount.value, minimumFrames.value)
  if (
    next.startFrame !== trimRange.value.startFrame ||
    next.endFrameExclusive !== trimRange.value.endFrameExclusive
  ) {
    trimRange.value = next
  }
  return next
}

function setStartFrame(frame: number) {
  const next = setTrimRange({ ...trimRange.value, startFrame: frame })
  seekToFrame(next.startFrame)
}

function setEndFrame(frame: number) {
  const next = setTrimRange({ ...trimRange.value, endFrameExclusive: frame })
  seekToFrame(next.endFrameExclusive - 1)
}

function commitStartFrame(value: number | undefined) {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    return
  }
  setStartFrame(uiRangeToBackend({ ...uiRange.value, startFrameInclusiveOneBased: value }).startFrame)
}

function commitEndFrame(value: number | undefined) {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    return
  }
  setEndFrame(uiRangeToBackend({ ...uiRange.value, endFrameInclusiveOneBased: value }).endFrameExclusive)
}

function commitStartTime(value: string | number) {
  const seconds = parseTrimTimestamp(String(value))
  if (seconds === null) {
    return
  }
  setStartFrame(secondsToFrame(seconds, fps.value, frameCount.value))
}

function commitEndTime(value: string | number) {
  const seconds = parseTrimTimestamp(String(value))
  if (seconds === null) {
    return
  }
  setEndFrame(secondsToFrame(seconds, fps.value, frameCount.value))
}

function setStartAtCurrent() {
  setStartFrame(currentFrame.value)
}

function setEndAtCurrent() {
  setEndFrame(currentFrame.value + 1)
}

function resetFullRange() {
  setTrimRange({ startFrame: 0, endFrameExclusive: frameCount.value })
  seekToFrame(0)
}

function togglePreview() {
  const video = videoRef.value
  if (!video) {
    return
  }
  if (previewing.value) {
    video.pause()
    previewing.value = false
    return
  }
  seekToFrame(trimRange.value.startFrame)
  previewing.value = true
  void video.play()
}

async function submitTrim() {
  if (!sourceVideo.value || submitDisabled.value) {
    return
  }
  submitting.value = true
  const sanitizedName = sanitizeTrimOutputName(outputName.value, sourceVideo.value.original_filename || sourceVideo.value.name)
  outputName.value = sanitizedName
  if (rememberHideSourceChoice.value) {
    writeHideSourceAfterTrimPreference(hideSourceAfterSuccess.value)
  }
  const response = await store.trimVideo(
    sourceVideo.value.id,
    buildTrimPayload(trimRange.value, sanitizedName, acknowledged.value, hideSourceAfterSuccess.value),
  )
  submitting.value = false
  if (!response) {
    ElMessage.error(store.error || t('videoTrim.failed'))
    return
  }
  trimResponseId.value = response.trimmed_video_id
  if (response.source_video_hidden && hideSourceAfterSuccess.value) {
    ElMessage.success(t('videoTrim.trimSucceededSourceHidden'))
  } else if (response.source_video_hidden) {
    ElMessage.success(t('videoTrim.sourceAlreadyHidden'))
  } else {
    ElMessage.success(t('videoTrim.trimSucceededSourceVisible'))
  }
}
</script>

<template>
  <main class="workspace">
    <AppSidebar :subtitle="t('research.subtitle')" />
    <section class="content research-trim-page">
      <header class="research-trim-header">
        <el-button text @click="router.push('/research/videos')">
          <el-icon><ArrowLeft /></el-icon>
          {{ t('research.videosTitle') }}
        </el-button>
        <div>
          <p class="eyebrow">{{ t('videoTrim.title') }}</p>
          <h2 :title="sourceVideo?.name">{{ sourceVideo?.name || t('videoTrim.sourceVideo') }}</h2>
        </div>
      </header>

      <el-alert v-if="store.error" :title="store.error" type="error" show-icon />

      <section v-if="sourceVideo" class="research-trim-workbench">
        <div class="research-trim-video-panel">
          <video
            ref="videoRef"
            class="research-trim-video"
            :src="sourceVideo.file_url"
            controls
            playsinline
            @timeupdate="handleTimeUpdate"
            @loadedmetadata="handleTimeUpdate"
          />
          <div class="research-trim-playback">
            <el-button @click="seekToFrame(currentFrame - 1)">{{ t('video.previousFrame') }}</el-button>
            <el-button @click="videoRef?.paused ? videoRef.play() : videoRef?.pause()">
              {{ videoRef?.paused ? t('video.play') : t('video.pause') }}
            </el-button>
            <VideoPlaybackRateControl compact />
            <el-button @click="seekToFrame(currentFrame + 1)">{{ t('video.nextFrame') }}</el-button>
            <el-input-number v-model="currentFrame" :min="0" :max="frameCount - 1" size="small" @change="seekToFrame(Number(currentFrame))" />
            <span>{{ t('videoTrim.currentFrame', { frame: currentFrame + 1, total: frameCount }) }}</span>
          </div>
          <VideoTrimTimeline
            v-model="trimRange"
            :frame-count="frameCount"
            :current-frame="currentFrame"
            :minimum-frames="minimumFrames"
            @seek="seekToFrame"
          />
        </div>

        <aside class="research-trim-editor">
          <section class="research-trim-card">
            <h3>{{ t('videoTrim.keepRange') }}</h3>
            <div class="research-trim-form-grid">
              <label>
                <span>{{ t('videoTrim.startFrame') }}</span>
                <el-input-number :model-value="startFrameInput" :min="1" :max="frameCount" @change="commitStartFrame" />
              </label>
              <label>
                <span>{{ t('videoTrim.startTime') }}</span>
                <el-input :model-value="startTimeText" @change="commitStartTime" />
              </label>
              <label>
                <span>{{ t('videoTrim.endFrameInclusive') }}</span>
                <el-input-number :model-value="endFrameInput" :min="1" :max="frameCount" @change="commitEndFrame" />
              </label>
              <label>
                <span>{{ t('videoTrim.endTime') }}</span>
                <el-input :model-value="endTimeText" @change="commitEndTime" />
              </label>
            </div>
            <div class="research-trim-actions">
              <el-button @click="setStartAtCurrent">{{ t('videoTrim.setStartAtCurrent') }}</el-button>
              <el-button @click="setEndAtCurrent">{{ t('videoTrim.setEndAtCurrent') }}</el-button>
              <el-button @click="seekToFrame(trimRange.startFrame)">{{ t('videoTrim.goToStart') }}</el-button>
              <el-button @click="seekToFrame(trimRange.endFrameExclusive - 1)">{{ t('videoTrim.goToEnd') }}</el-button>
              <el-button @click="resetFullRange">{{ t('videoTrim.resetFullRange') }}</el-button>
              <el-button type="primary" plain @click="togglePreview">
                {{ previewing ? t('videoTrim.stopPreview') : t('videoTrim.previewSelection') }}
              </el-button>
            </div>
            <el-alert v-if="rangeError" :title="rangeError" type="warning" show-icon />
          </section>

          <section class="research-trim-card">
            <h3>{{ t('videoTrim.summary') }}</h3>
            <dl class="research-trim-summary">
              <div><dt>{{ t('videoTrim.originalDuration') }}</dt><dd>{{ formatTrimTimestamp(originalDurationSeconds) }}</dd></div>
              <div><dt>{{ t('videoTrim.originalFrames') }}</dt><dd>{{ frameCount }}</dd></div>
              <div><dt>{{ t('videoTrim.outputDuration') }}</dt><dd>{{ formatTrimTimestamp(outputDurationSeconds) }}</dd></div>
              <div><dt>{{ t('videoTrim.outputFrames') }}</dt><dd>{{ outputFrames }}</dd></div>
              <div><dt>{{ t('videoTrim.trimmedFromStart') }}</dt><dd>{{ formatTrimTimestamp(removedStartSeconds) }}</dd></div>
              <div><dt>{{ t('videoTrim.trimmedFromEnd') }}</dt><dd>{{ formatTrimTimestamp(removedEndSeconds) }}</dd></div>
            </dl>
          </section>

          <section class="research-trim-card">
            <h3>{{ t('videoTrim.create') }}</h3>
            <el-input v-model="outputName" :placeholder="t('videoTrim.outputName')" />
            <el-alert
              v-if="hasLinkedData"
              type="warning"
              show-icon
              :title="t('videoTrim.annotationsWarning')"
              :description="t('videoTrim.annotationsNotCopied')"
            />
            <el-alert v-else type="info" show-icon :title="t('videoTrim.originalPreserved')" />
            <div v-if="hasLinkedData && trimInfo" class="research-trim-linked-data">
              <span>{{ t('videoTrim.frameAnnotations', { count: trimInfo.linked_data.frame_annotation_count }) }}</span>
              <span>{{ t('videoTrim.phaseAnnotationSets', { count: trimInfo.linked_data.phase_annotation_set_count }) }}</span>
              <span>{{ t('videoTrim.phaseSegments', { count: trimInfo.linked_data.phase_segment_count }) }}</span>
              <span>{{ t('videoTrim.skillAssessments', { count: trimInfo.linked_data.skill_assessment_count }) }}</span>
              <span>{{ t('videoTrim.skillEvidence', { count: trimInfo.linked_data.skill_evidence_count }) }}</span>
            </div>
            <el-checkbox v-if="hasLinkedData" v-model="acknowledged">
              {{ t('videoTrim.annotationsAcknowledgement') }}
            </el-checkbox>
            <div class="research-trim-output-options" data-storage-key="researchVideoTrim.hideSourceAfterSuccess">
              <el-checkbox v-model="hideSourceAfterSuccess" :disabled="saving || submitting">
                {{ t('videoTrim.hideSourceAfterSuccess') }}
              </el-checkbox>
              <p>{{ t('videoTrim.hideSourceAfterSuccessDescription') }}</p>
              <el-checkbox v-model="rememberHideSourceChoice" :disabled="saving || submitting">
                {{ t('videoTrim.rememberHideSourceChoice') }}
              </el-checkbox>
            </div>
            <el-button type="primary" :loading="saving || submitting" :disabled="submitDisabled" @click="submitTrim">
              {{ t('videoTrim.create') }}
            </el-button>
            <el-button v-if="trimResponseId" type="success" @click="router.push(`/research/videos/${trimResponseId}/annotate`)">
              <el-icon><VideoPlay /></el-icon>
              {{ t('videoTrim.openTrimmedVideo') }}
            </el-button>
          </section>
        </aside>
      </section>

      <div v-else v-loading="loading" class="research-empty-state">
        {{ t('common.loading') }}
      </div>
    </section>
  </main>
</template>
