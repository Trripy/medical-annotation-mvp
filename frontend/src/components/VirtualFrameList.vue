<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import type { ResearchVideoFrame } from '../stores/researchVideos'
import { getVirtualRange } from '../utils/researchVideoLayout'

const DEFAULT_ROW_HEIGHT = 54
const DEFAULT_OVERSCAN = 8

const props = withDefaults(defineProps<{
  totalCount: number
  selectedFrameIndex: number
  getFrame: (index: number) => ResearchVideoFrame | undefined
  rowHeight?: number
  overscan?: number
}>(), {
  rowHeight: DEFAULT_ROW_HEIGHT,
  overscan: DEFAULT_OVERSCAN,
})

const emit = defineEmits<{
  requestRange: [startIndex: number, endIndex: number]
  select: [index: number]
}>()

const viewportRef = ref<HTMLElement | null>(null)
const scrollTop = ref(0)
const viewportHeight = ref(0)
let viewportResizeObserver: ResizeObserver | null = null
type ScrollAlign = 'auto' | 'center'

const virtualRange = computed(() => getVirtualRange({
  scrollTop: scrollTop.value,
  viewportHeight: viewportHeight.value,
  itemCount: props.totalCount,
  rowHeight: props.rowHeight,
  overscan: props.overscan,
}))

const visibleFrames = computed(() => {
  const entries: Array<{ frame: ResearchVideoFrame | undefined; index: number }> = []
  for (let index = virtualRange.value.startIndex; index <= virtualRange.value.endIndex; index += 1) {
    entries.push({ frame: props.getFrame(index), index })
  }
  return entries
})

onMounted(async () => {
  await nextTick()
  updateViewportHeight()
  initializeViewportObserver()
  scrollToIndex(props.selectedFrameIndex)
})

onBeforeUnmount(() => {
  viewportResizeObserver?.disconnect()
  viewportResizeObserver = null
})

watch(
  () => props.selectedFrameIndex,
  (nextIndex, previousIndex) => {
    const visibleRowCount = props.rowHeight > 0
      ? Math.max(1, Math.floor(viewportHeight.value / props.rowHeight))
      : 1
    const shouldCenter = previousIndex === undefined || Math.abs(nextIndex - previousIndex) > visibleRowCount
    scrollToIndex(nextIndex, { align: shouldCenter ? 'center' : 'auto' })
  },
)

watch(
  () => props.totalCount,
  () => {
    updateViewportHeight()
    scrollToIndex(props.selectedFrameIndex)
  },
)
watch(
  () => [virtualRange.value.startIndex, virtualRange.value.endIndex, props.totalCount],
  () => {
    if (virtualRange.value.endIndex >= virtualRange.value.startIndex) {
      emit('requestRange', virtualRange.value.startIndex, virtualRange.value.endIndex)
    }
  },
  { immediate: true },
)

function initializeViewportObserver() {
  viewportResizeObserver?.disconnect()
  if (!viewportRef.value || typeof ResizeObserver === 'undefined') {
    return
  }

  viewportResizeObserver = new ResizeObserver(() => {
    updateViewportHeight()
  })
  viewportResizeObserver.observe(viewportRef.value)
}

function updateViewportHeight() {
  viewportHeight.value = viewportRef.value?.clientHeight ?? 0
}

function onScroll(event: Event) {
  const target = event.target as HTMLElement
  scrollTop.value = target.scrollTop
}

function scrollToIndex(index: number, options: { align?: ScrollAlign } = {}) {
  if (!viewportRef.value || index < 0 || index >= props.totalCount) {
    return
  }

  const rowTop = index * props.rowHeight
  const rowBottom = rowTop + props.rowHeight
  const currentTop = viewportRef.value.scrollTop
  const currentBottom = currentTop + viewportHeight.value
  if (options.align === 'center') {
    const centeredScrollTop = Math.max(0, rowTop - Math.max(0, (viewportHeight.value - props.rowHeight) / 2))
    viewportRef.value.scrollTop = centeredScrollTop
    scrollTop.value = centeredScrollTop
    return
  }

  if (rowTop < currentTop) {
    viewportRef.value.scrollTop = rowTop
    scrollTop.value = rowTop
    return
  }

  if (rowBottom > currentBottom) {
    const nextScrollTop = Math.max(0, rowBottom - viewportHeight.value)
    viewportRef.value.scrollTop = nextScrollTop
    scrollTop.value = nextScrollTop
  }
}

function formatTimestamp(timestampMs: number) {
  const totalSeconds = Math.floor(timestampMs / 1000)
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  const milliseconds = Math.floor((timestampMs % 1000) / 10)
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}.${String(milliseconds).padStart(2, '0')}`
}

defineExpose({
  scrollToIndex,
})
</script>

<template>
  <div
    ref="viewportRef"
    class="frame-list research-frame-list virtual-frame-list"
    @scroll="onScroll"
  >
    <div class="virtual-frame-list-spacer" :style="{ height: `${virtualRange.totalHeight}px` }">
      <div
        class="virtual-frame-list-window"
        :style="{ transform: `translateY(${virtualRange.offsetTop}px)` }"
      >
        <div
          v-for="entry in visibleFrames"
          :key="entry.frame?.id ?? `frame-${entry.index}`"
          class="virtual-frame-list-row"
          :style="{ height: `${rowHeight}px` }"
        >
          <button
            class="frame-choice virtual-frame-choice"
            :class="{ active: selectedFrameIndex === entry.index }"
            type="button"
            @click="emit('select', entry.index)"
          >
            <span>
              {{ entry.frame ? `${entry.index + 1}. ${entry.frame.filename}` : `${entry.index + 1}. Loading frame...` }}
            </span>
            <span class="frame-choice-badge review">
              {{ entry.frame ? formatTimestamp(entry.frame.timestamp_ms) : '--:--.--' }}
            </span>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
