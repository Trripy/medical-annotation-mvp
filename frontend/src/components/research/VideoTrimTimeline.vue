<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { clampTrimRange, getTimelineGeometry, type TrimRange } from '../../utils/videoTrim'

const props = defineProps<{
  frameCount: number
  currentFrame: number
  minimumFrames: number
}>()

const range = defineModel<TrimRange>({ required: true })
const emit = defineEmits<{
  seek: [frame: number]
}>()

const { t } = useI18n()
const trackRef = ref<HTMLElement | null>(null)
const draggingHandle = ref<'start' | 'end' | null>(null)
let activePointerId: number | null = null

const geometry = computed(() => getTimelineGeometry({
  frameCount: props.frameCount,
  startFrame: range.value.startFrame,
  endFrameExclusive: range.value.endFrameExclusive,
  currentFrame: props.currentFrame,
}))

function frameFromClientX(clientX: number) {
  const rect = trackRef.value?.getBoundingClientRect()
  if (!rect || rect.width <= 0) {
    return 0
  }
  const ratio = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width))
  return Math.round(ratio * props.frameCount)
}

function updateHandle(handle: 'start' | 'end', frame: number) {
  const next = handle === 'start'
    ? { ...range.value, startFrame: frame }
    : { ...range.value, endFrameExclusive: frame }
  range.value = clampTrimRange(next, props.frameCount, props.minimumFrames)
  emit('seek', handle === 'start' ? range.value.startFrame : range.value.endFrameExclusive - 1)
}

function startDrag(handle: 'start' | 'end', event: PointerEvent) {
  draggingHandle.value = handle
  activePointerId = event.pointerId
  ;(event.currentTarget as HTMLElement).setPointerCapture(event.pointerId)
  updateHandle(handle, frameFromClientX(event.clientX))
}

function moveDrag(event: PointerEvent) {
  if (!draggingHandle.value || activePointerId !== event.pointerId) {
    return
  }
  updateHandle(draggingHandle.value, frameFromClientX(event.clientX))
}

function stopDrag(event: PointerEvent) {
  if (activePointerId === event.pointerId) {
    try {
      ;(event.currentTarget as HTMLElement).releasePointerCapture(event.pointerId)
    } catch {
      // Pointer capture can already be released by the browser.
    }
  }
  draggingHandle.value = null
  activePointerId = null
}

function adjustByKeyboard(handle: 'start' | 'end', event: KeyboardEvent) {
  const step = event.shiftKey ? 10 : 1
  if (event.key === 'ArrowLeft') {
    updateHandle(handle, (handle === 'start' ? range.value.startFrame : range.value.endFrameExclusive) - step)
  } else if (event.key === 'ArrowRight') {
    updateHandle(handle, (handle === 'start' ? range.value.startFrame : range.value.endFrameExclusive) + step)
  } else if (event.key === 'Home') {
    updateHandle(handle, handle === 'start' ? 0 : range.value.startFrame + props.minimumFrames)
  } else if (event.key === 'End') {
    updateHandle(handle, handle === 'start' ? range.value.endFrameExclusive - props.minimumFrames : props.frameCount)
  } else {
    return
  }
  event.preventDefault()
}

onBeforeUnmount(() => {
  draggingHandle.value = null
  activePointerId = null
})
</script>

<template>
  <div class="video-trim-timeline">
    <div
      ref="trackRef"
      class="video-trim-track"
      @pointermove="moveDrag"
      @pointerup="stopDrag"
      @pointercancel="stopDrag"
    >
      <div class="video-trim-removed left" :style="{ width: `${geometry.startPercent}%` }" />
      <div
        class="video-trim-kept"
        :style="{ left: `${geometry.startPercent}%`, width: `${geometry.selectionWidthPercent}%` }"
      />
      <div class="video-trim-removed right" :style="{ left: `${geometry.endPercent}%`, width: `${100 - geometry.endPercent}%` }" />
      <div class="video-trim-playhead" :style="{ left: `${geometry.playheadPercent}%` }" />
      <button
        class="video-trim-handle start"
        type="button"
        :aria-label="t('videoTrim.startFrame')"
        :style="{ left: `${geometry.startPercent}%` }"
        @pointerdown.prevent="startDrag('start', $event)"
        @keydown="adjustByKeyboard('start', $event)"
      />
      <button
        class="video-trim-handle end"
        type="button"
        :aria-label="t('videoTrim.endFrameInclusive')"
        :style="{ left: `${geometry.endPercent}%` }"
        @pointerdown.prevent="startDrag('end', $event)"
        @keydown="adjustByKeyboard('end', $event)"
      />
    </div>
  </div>
</template>
