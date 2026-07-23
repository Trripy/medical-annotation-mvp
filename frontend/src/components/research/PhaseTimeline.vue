<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import type { ResearchPhaseSegment } from '../../types/researchPhase'
import {
  calculateSegmentGeometry,
  calculateTimelineWidth,
  calculateVisibleFrameRange,
  clampFrame,
  frameToPixel,
  normalizeFramesPerPixel,
  pixelToFrame,
} from '../../utils/researchPhaseTimeline'

type DragEdge = 'left' | 'right'
type SegmentPatch = {
  start_frame?: number
  end_frame_exclusive?: number | null
}

const props = defineProps<{
  currentFrameIndex: number
  frameCount: number
  readonly?: boolean
  segments: ResearchPhaseSegment[]
  selectedSegmentId: number | null
}>()

const { t } = useI18n()

const emit = defineEmits<{
  seek: [frameIndex: number]
  selectSegment: [segmentId: number]
  updateSegmentBoundary: [payload: { segmentId: number; patch: SegmentPatch }]
}>()

const viewportRef = ref<HTMLElement | null>(null)
const framesPerPixel = ref(6)
const viewportWidth = ref(0)
const dragPreview = ref<Record<number, { start_frame: number; end_frame_exclusive: number | null }>>({})

let viewportResizeObserver: ResizeObserver | null = null
let dragState: {
  segmentId: number
  edge: DragEdge
  minFrame: number
  maxFrame: number
  frameCount: number
  pointerId: number
  startFrame: number
  initialValue: number
  pendingFrame: number
  animationFrame: number
} | null = null

const timelineInput = computed(() => ({
  frameCount: props.frameCount,
  framesPerPixel: framesPerPixel.value,
}))

const sortedSegments = computed(() => (
  props.segments.slice().sort((left, right) => left.start_frame - right.start_frame || left.id - right.id)
))

const segmentById = computed(() => new Map(sortedSegments.value.map((segment) => [segment.id, segment])))
const segmentIndexById = computed(() => new Map(sortedSegments.value.map((segment, index) => [segment.id, index])))
const timelineWidth = computed(() => calculateTimelineWidth(timelineInput.value))
const visibleRange = computed(() => calculateVisibleFrameRange(
  viewportRef.value?.scrollLeft ?? 0,
  viewportWidth.value,
  timelineInput.value,
))

const renderedSegments = computed(() => sortedSegments.value.map((segment) => {
  const preview = dragPreview.value[segment.id]
  const geometry = calculateSegmentGeometry(
    preview
      ? { ...segment, ...preview }
      : segment,
    timelineInput.value,
  )
  return {
    segment,
    preview,
    geometry,
    isOpen: (preview?.end_frame_exclusive ?? segment.end_frame_exclusive) === null,
    isSelected: props.selectedSegmentId === segment.id,
  }
}))

const playheadLeft = computed(() => frameToPixel(props.currentFrameIndex, timelineInput.value))

onMounted(async () => {
  await nextTick()
  updateViewportWidth()
  fitTimeline()
  initializeViewportObserver()
})

onBeforeUnmount(() => {
  viewportResizeObserver?.disconnect()
  viewportResizeObserver = null
  stopDragListeners()
})

watch(
  () => props.frameCount,
  async () => {
    await nextTick()
    fitTimeline()
  },
)

function initializeViewportObserver() {
  viewportResizeObserver?.disconnect()
  if (!viewportRef.value || typeof ResizeObserver === 'undefined') {
    return
  }
  viewportResizeObserver = new ResizeObserver(() => {
    updateViewportWidth()
  })
  viewportResizeObserver.observe(viewportRef.value)
}

function updateViewportWidth() {
  viewportWidth.value = viewportRef.value?.clientWidth ?? 0
}

function fitTimeline() {
  if (!viewportRef.value || props.frameCount <= 0) {
    framesPerPixel.value = 6
    return
  }
  const availableWidth = Math.max(viewportRef.value.clientWidth - 24, 1)
  framesPerPixel.value = normalizeFramesPerPixel(props.frameCount / availableWidth)
}

function zoomIn() {
  framesPerPixel.value = Math.max(0.25, framesPerPixel.value / 1.5)
}

function zoomOut() {
  framesPerPixel.value = Math.min(Math.max(props.frameCount, 1), framesPerPixel.value * 1.5)
}

function scrollToFrame(frameIndex: number, behavior: ScrollBehavior = 'smooth') {
  if (!viewportRef.value) {
    return
  }
  const targetLeft = Math.max(0, frameToPixel(frameIndex, timelineInput.value) - (viewportRef.value.clientWidth / 2))
  viewportRef.value.scrollTo({
    left: targetLeft,
    behavior,
  })
}

function scrollToSelectedSegment() {
  const segment = props.selectedSegmentId === null ? null : segmentById.value.get(props.selectedSegmentId) ?? null
  if (!segment) {
    scrollToFrame(props.currentFrameIndex)
    return
  }
  scrollToFrame(segment.start_frame)
}

function handleCanvasClick(event: MouseEvent) {
  if (!viewportRef.value || props.frameCount <= 0) {
    return
  }
  const rect = viewportRef.value.getBoundingClientRect()
  const frameIndex = pixelToFrame(
    viewportRef.value.scrollLeft + event.clientX - rect.left,
    timelineInput.value,
  )
  emit('seek', Math.min(frameIndex, Math.max(props.frameCount - 1, 0)))
}

function getNeighborSegments(segmentId: number) {
  const index = segmentIndexById.value.get(segmentId)
  if (index === undefined) {
    return {
      previous: null as ResearchPhaseSegment | null,
      next: null as ResearchPhaseSegment | null,
    }
  }
  return {
    previous: index > 0 ? sortedSegments.value[index - 1] : null,
    next: index < sortedSegments.value.length - 1 ? sortedSegments.value[index + 1] : null,
  }
}

function startBoundaryDrag(segment: ResearchPhaseSegment, edge: DragEdge, event: PointerEvent) {
  if (props.readonly || props.frameCount <= 0) {
    return
  }
  const { previous, next } = getNeighborSegments(segment.id)
  const closedEnd = segment.end_frame_exclusive ?? props.frameCount
  const minFrame = edge === 'left'
    ? previous?.end_frame_exclusive ?? 0
    : segment.start_frame + 1
  const maxFrame = edge === 'left'
    ? Math.max(segment.start_frame, closedEnd - 1)
    : next?.start_frame ?? props.frameCount
  const initialValue = edge === 'left' ? segment.start_frame : closedEnd
  dragState = {
    segmentId: segment.id,
    edge,
    minFrame,
    maxFrame,
    frameCount: props.frameCount,
    pointerId: event.pointerId,
    startFrame: initialValue,
    initialValue,
    pendingFrame: initialValue,
    animationFrame: 0,
  }
  window.addEventListener('pointermove', handleBoundaryDragMove)
  window.addEventListener('pointerup', finalizeBoundaryDrag)
  window.addEventListener('pointercancel', cancelBoundaryDrag)
  window.addEventListener('keydown', handleKeydownCancel)
}

function scheduleDragPreview() {
  if (!dragState || dragState.animationFrame) {
    return
  }
  dragState.animationFrame = window.requestAnimationFrame(() => {
    if (!dragState) {
      return
    }
    const segment = segmentById.value.get(dragState.segmentId)
    if (!segment) {
      return
    }
    const nextPreviewValue = clampFrame(dragState.pendingFrame, dragState.frameCount)
    dragPreview.value = {
      ...dragPreview.value,
      [segment.id]: {
        start_frame: dragState.edge === 'left' ? nextPreviewValue : segment.start_frame,
        end_frame_exclusive: dragState.edge === 'right'
          ? nextPreviewValue
          : segment.end_frame_exclusive,
      },
    }
    dragState.animationFrame = 0
  })
}

function handleBoundaryDragMove(event: PointerEvent) {
  if (!dragState || !viewportRef.value || event.pointerId !== dragState.pointerId) {
    return
  }
  const rect = viewportRef.value.getBoundingClientRect()
  const frameValue = pixelToFrame(
    viewportRef.value.scrollLeft + event.clientX - rect.left,
    timelineInput.value,
  )
  dragState.pendingFrame = Math.max(dragState.minFrame, Math.min(frameValue, dragState.maxFrame))
  scheduleDragPreview()
}

function stopDragListeners() {
  if (dragState?.animationFrame) {
    window.cancelAnimationFrame(dragState.animationFrame)
  }
  dragState = null
  window.removeEventListener('pointermove', handleBoundaryDragMove)
  window.removeEventListener('pointerup', finalizeBoundaryDrag)
  window.removeEventListener('pointercancel', cancelBoundaryDrag)
  window.removeEventListener('keydown', handleKeydownCancel)
}

function cancelBoundaryDrag() {
  dragPreview.value = {}
  stopDragListeners()
}

function handleKeydownCancel(event: KeyboardEvent) {
  if (event.key === 'Escape') {
    cancelBoundaryDrag()
  }
}

function finalizeBoundaryDrag(event: PointerEvent) {
  if (!dragState || event.pointerId !== dragState.pointerId) {
    return
  }
  const segment = segmentById.value.get(dragState.segmentId)
  const nextFrame = dragState.pendingFrame
  const changed = nextFrame !== dragState.initialValue
  const payload = dragState.edge === 'left'
    ? { start_frame: nextFrame }
    : { end_frame_exclusive: nextFrame }
  cancelBoundaryDrag()
  if (!segment || !changed) {
    return
  }
  emit('updateSegmentBoundary', {
    segmentId: segment.id,
    patch: payload,
  })
}

defineExpose({
  fitTimeline,
  scrollToFrame,
  scrollToSelectedSegment,
})
</script>

<template>
  <section class="phase-timeline">
    <header class="phase-timeline-header">
      <div>
        <p class="phase-timeline-eyebrow">{{ t('phaseAnnotation.timeline') }}</p>
        <strong>{{ frameCount }} {{ t('common.frames') }}</strong>
        <span>
          Visible {{ visibleRange.startFrame + 1 }}-{{ Math.max(visibleRange.startFrame + 1, visibleRange.endFrameExclusive) }}
        </span>
      </div>
      <div class="phase-timeline-actions">
        <button type="button" @click="zoomIn">{{ t('phaseAnnotation.zoomIn') }}</button>
        <button type="button" @click="zoomOut">{{ t('phaseAnnotation.zoomOut') }}</button>
        <button type="button" @click="fitTimeline">{{ t('phaseAnnotation.fitVideo') }}</button>
        <button type="button" @click="scrollToFrame(currentFrameIndex)">{{ t('phaseAnnotation.scrollToPlayhead') }}</button>
        <button type="button" @click="scrollToSelectedSegment">{{ t('phaseAnnotation.scrollToSelection') }}</button>
      </div>
    </header>

    <div ref="viewportRef" class="phase-timeline-viewport" @click="handleCanvasClick">
      <div class="phase-timeline-canvas" :style="{ width: `${timelineWidth}px` }">
        <div class="phase-timeline-grid"></div>

        <button
          v-for="entry in renderedSegments"
          :key="entry.segment.id"
          class="phase-timeline-segment"
          :class="{
            'is-selected': entry.isSelected,
            'is-open': entry.isOpen,
          }"
          :style="{
            left: `${entry.geometry.left}px`,
            width: `${entry.geometry.width}px`,
            '--phase-segment-color': entry.segment.phase_label.color,
          }"
          type="button"
          @click.stop="emit('selectSegment', entry.segment.id)"
          @dblclick.stop="emit('seek', entry.segment.start_frame)"
        >
          <span class="phase-timeline-segment-label">
            {{ entry.segment.phase_label.name }}
          </span>
          <span class="phase-timeline-segment-range">
            {{ entry.segment.start_frame + 1 }}-{{ entry.segment.end_frame_exclusive ?? frameCount }}
          </span>
          <span
            v-if="!readonly"
            class="phase-timeline-handle is-left"
            @pointerdown.stop="startBoundaryDrag(entry.segment, 'left', $event)"
          ></span>
          <span
            v-if="!readonly && entry.segment.end_frame_exclusive !== null"
            class="phase-timeline-handle is-right"
            @pointerdown.stop="startBoundaryDrag(entry.segment, 'right', $event)"
          ></span>
        </button>

        <div class="phase-timeline-playhead" :style="{ left: `${playheadLeft}px` }"></div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.phase-timeline {
  display: flex;
  flex-direction: column;
  gap: 0.9rem;
  padding: 1rem 1.1rem;
  border-radius: 1rem;
  background: rgba(15, 23, 42, 0.82);
  border: 1px solid rgba(148, 163, 184, 0.18);
}

.phase-timeline-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 1rem;
  flex-wrap: wrap;
}

.phase-timeline-header strong,
.phase-timeline-header span,
.phase-timeline-eyebrow {
  display: block;
}

.phase-timeline-eyebrow {
  margin: 0 0 0.2rem;
  font-size: 0.78rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: rgba(125, 211, 252, 0.84);
}

.phase-timeline-header strong {
  color: #f8fafc;
}

.phase-timeline-header span {
  color: rgba(148, 163, 184, 0.92);
  font-size: 0.88rem;
}

.phase-timeline-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.55rem;
}

.phase-timeline-actions button {
  padding: 0.55rem 0.8rem;
  border-radius: 0.85rem;
  border: 1px solid rgba(148, 163, 184, 0.22);
  background: rgba(30, 41, 59, 0.78);
  color: #e2e8f0;
}

.phase-timeline-viewport {
  overflow-x: auto;
  overflow-y: hidden;
  padding-bottom: 0.35rem;
}

.phase-timeline-canvas {
  position: relative;
  min-height: 128px;
  border-radius: 0.85rem;
  background:
    linear-gradient(180deg, rgba(15, 23, 42, 0.48), rgba(15, 23, 42, 0.88)),
    repeating-linear-gradient(
      90deg,
      rgba(148, 163, 184, 0.06) 0,
      rgba(148, 163, 184, 0.06) 1px,
      transparent 1px,
      transparent 24px
    );
  border: 1px solid rgba(148, 163, 184, 0.16);
}

.phase-timeline-grid {
  position: absolute;
  inset: 0;
  border-radius: inherit;
  background:
    linear-gradient(180deg, transparent 49%, rgba(148, 163, 184, 0.08) 50%, transparent 51%);
  pointer-events: none;
}

.phase-timeline-segment {
  position: absolute;
  top: 36px;
  height: 54px;
  border-radius: 0.8rem;
  border: 1px solid rgba(255, 255, 255, 0.16);
  background:
    linear-gradient(135deg, color-mix(in srgb, var(--phase-segment-color) 62%, #0f172a), rgba(15, 23, 42, 0.94));
  color: #f8fafc;
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 0.2rem;
  padding: 0.55rem 0.8rem;
  text-align: left;
  overflow: hidden;
}

.phase-timeline-segment.is-selected {
  box-shadow: 0 0 0 2px rgba(125, 211, 252, 0.58);
}

.phase-timeline-segment.is-open {
  border-style: dashed;
}

.phase-timeline-segment-label,
.phase-timeline-segment-range {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.phase-timeline-segment-label {
  font-weight: 700;
}

.phase-timeline-segment-range {
  font-size: 0.82rem;
  color: rgba(226, 232, 240, 0.88);
}

.phase-timeline-handle {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 10px;
  cursor: ew-resize;
}

.phase-timeline-handle.is-left {
  left: 0;
}

.phase-timeline-handle.is-right {
  right: 0;
}

.phase-timeline-playhead {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 2px;
  background: linear-gradient(180deg, #fb7185, #f97316);
  box-shadow: 0 0 12px rgba(249, 115, 22, 0.48);
  pointer-events: none;
}

@media (max-width: 900px) {
  .phase-timeline-header {
    flex-direction: column;
  }
}
</style>
