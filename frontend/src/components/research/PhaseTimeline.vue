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
  getFocusedVisibleRange,
  getPhaseSegmentPixelWidth,
  getPhaseSegmentPresentation,
  getPhaseSegmentTooltip,
  getVisiblePhaseCoverageGaps,
  hitTestPhaseSegment,
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
  fps?: number | null
  frameCount: number
  readonly?: boolean
  segments: ResearchPhaseSegment[]
  selectedSegmentId: number | null
}>()

const { t } = useI18n()

const emit = defineEmits<{
  seek: [frameIndex: number]
  selectSegment: [segmentId: number]
  clearSelection: []
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
  const widthPx = getPhaseSegmentPixelWidth(geometry)
  const presentation = getPhaseSegmentPresentation(widthPx)
  const tooltip = getPhaseSegmentTooltip(segment, props.frameCount, props.fps)
  return {
    segment,
    preview,
    geometry,
    widthPx,
    presentation,
    tooltip,
    isOpen: (preview?.end_frame_exclusive ?? segment.end_frame_exclusive) === null,
    isSelected: props.selectedSegmentId === segment.id,
  }
}))

const renderedCoverageGaps = computed(() => getVisiblePhaseCoverageGaps(
  { startFrame: 0, endFrameExclusive: props.frameCount },
  sortedSegments.value,
).map((gap) => ({
  gap,
  geometry: calculateSegmentGeometry(
    { start_frame: gap.startFrame, end_frame_exclusive: gap.endFrameExclusive },
    timelineInput.value,
  ),
})))

const playheadLeft = computed(() => frameToPixel(props.currentFrameIndex, timelineInput.value))
const selectedFloatingLabel = computed(() => {
  const entry = renderedSegments.value.find((segmentEntry) => segmentEntry.isSelected)
  if (!entry || (entry.presentation !== 'marker-only' && entry.presentation !== 'compact')) {
    return null
  }
  const center = entry.geometry.left + (entry.geometry.width / 2)
  const clampedCenter = Math.max(24, Math.min(timelineWidth.value - 24, center))
  return {
    left: clampedCenter,
    text: `${entry.segment.phase_label.name} · ${entry.segment.start_frame + 1}-${entry.segment.end_frame_exclusive ?? props.frameCount}`,
  }
})

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

function focusSelectedSegment() {
  const segment = props.selectedSegmentId === null ? null : segmentById.value.get(props.selectedSegmentId) ?? null
  if (!segment) {
    scrollToFrame(props.currentFrameIndex)
    return
  }
  if (!viewportRef.value) {
    return
  }
  const focused = getFocusedVisibleRange({
    segment,
    frameCount: props.frameCount,
    fps: props.fps,
    viewportWidth: Math.max(1, viewportRef.value.clientWidth - 24),
  })
  framesPerPixel.value = focused.framesPerPixel
  void nextTick(() => {
    viewportRef.value?.scrollTo({
      left: frameToPixel(focused.startFrame, timelineInput.value),
      behavior: 'smooth',
    })
  })
}

function scrollToSelectedSegment() {
  focusSelectedSegment()
}

function handleCanvasClick(event: MouseEvent) {
  if (!viewportRef.value || props.frameCount <= 0) {
    return
  }
  const rect = viewportRef.value.getBoundingClientRect()
  const timelineX = viewportRef.value.scrollLeft + event.clientX - rect.left
  const hitSegment = hitTestPhaseSegment(
    timelineX,
    timelineWidth.value,
    0,
    props.frameCount,
    sortedSegments.value,
  )
  if (hitSegment) {
    emit('selectSegment', hitSegment.id)
    return
  }
  const frameIndex = pixelToFrame(timelineX, timelineInput.value)
  emit('seek', Math.min(frameIndex, Math.max(props.frameCount - 1, 0)))
}

function handleSegmentDblClick(segment: ResearchPhaseSegment) {
  emit('selectSegment', segment.id)
  void nextTick(() => {
    focusSelectedSegment()
  })
}

function handleSegmentKeydown(segment: ResearchPhaseSegment, event: KeyboardEvent) {
  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault()
    emit('selectSegment', segment.id)
  } else if (event.key === 'Escape') {
    event.preventDefault()
    emit('clearSelection')
  }
}

function formatTooltipTime(seconds: number) {
  const safeSeconds = Math.max(0, Number.isFinite(seconds) ? seconds : 0)
  const minutes = Math.floor(safeSeconds / 60)
  const wholeSeconds = Math.floor(safeSeconds % 60)
  const millis = Math.round((safeSeconds - Math.floor(safeSeconds)) * 1000)
  return `${String(minutes).padStart(2, '0')}:${String(wholeSeconds).padStart(2, '0')}.${String(millis).padStart(3, '0')}`
}

function segmentAriaLabel(entry: typeof renderedSegments.value[number]) {
  return `${t('phaseTimeline.selectedSegment')}: ${entry.segment.phase_label.name}, ${t('phaseTimeline.startFrame')} ${entry.tooltip.startFrameOneBased}, ${t('phaseTimeline.endFrame')} ${entry.tooltip.endFrameInclusiveOneBased}, ${t('phaseTimeline.durationFrames')} ${entry.tooltip.durationFrames}`
}

function gapTooltip(gap: { startFrame: number; endFrameExclusive: number; durationFrames: number }) {
  return `${t('phaseTimeline.unannotatedRange')}: ${gap.startFrame + 1}-${gap.endFrameExclusive} · ${t('phaseTimeline.durationFrames')} ${gap.durationFrames}`
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
  focusSelectedSegment,
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
        <button type="button" @click="focusSelectedSegment">{{ t('phaseTimeline.focusSelected') }}</button>
      </div>
    </header>

    <div ref="viewportRef" class="phase-timeline-viewport" @click="handleCanvasClick">
      <div class="phase-timeline-canvas" :style="{ width: `${timelineWidth}px` }">
        <div class="phase-timeline-grid"></div>

        <div class="phase-timeline-coverage-layer" aria-hidden="true">
          <div
            v-for="entry in renderedSegments"
            :key="`coverage-${entry.segment.id}`"
            class="phase-timeline-coverage-segment"
            :class="{ 'is-open': entry.isOpen }"
            :style="{
              left: `${entry.geometry.left}px`,
              width: `${entry.geometry.width}px`,
              '--phase-segment-color': entry.segment.phase_label.color,
            }"
          ></div>
        </div>

        <el-tooltip
          v-for="entry in renderedCoverageGaps"
          :key="`gap-${entry.gap.startFrame}-${entry.gap.endFrameExclusive}`"
          placement="top"
          teleported
        >
          <template #content>
            <div class="phase-timeline-tooltip">
              <strong>{{ t('phaseTimeline.unannotatedRange') }}</strong>
              <span>{{ t('phaseTimeline.startFrame') }}: {{ entry.gap.startFrame + 1 }}</span>
              <span>{{ t('phaseTimeline.endFrame') }}: {{ entry.gap.endFrameExclusive }}</span>
              <span>{{ t('phaseTimeline.durationFrames') }}: {{ entry.gap.durationFrames }}</span>
            </div>
          </template>
          <div
            class="phase-timeline-gap"
            :class="{ 'is-compact': entry.geometry.width < 48 }"
            :style="{
              left: `${entry.geometry.left}px`,
              width: `${entry.geometry.width}px`,
            }"
            :aria-label="gapTooltip(entry.gap)"
          >
            <span v-if="entry.geometry.width >= 64">{{ t('phaseTimeline.unannotated') }}</span>
          </div>
        </el-tooltip>

        <div
          v-if="selectedFloatingLabel"
          class="phase-timeline-selected-float"
          :style="{ left: `${selectedFloatingLabel.left}px` }"
        >
          {{ selectedFloatingLabel.text }}
        </div>

        <el-tooltip
          v-for="entry in renderedSegments"
          :key="entry.segment.id"
          placement="top"
          teleported
        >
          <template #content>
            <div class="phase-timeline-tooltip">
              <strong>{{ entry.tooltip.name }}</strong>
              <span>{{ t('phaseTimeline.startFrame') }}: {{ entry.tooltip.startFrameOneBased }}</span>
              <span>{{ t('phaseTimeline.endFrame') }}: {{ entry.tooltip.endFrameInclusiveOneBased }}</span>
              <span>{{ t('phaseTimeline.durationFrames') }}: {{ entry.tooltip.durationFrames }}</span>
              <span>{{ t('phaseTimeline.startTime') }}: {{ formatTooltipTime(entry.tooltip.startTimeSeconds) }}</span>
              <span>{{ t('phaseTimeline.endTime') }}: {{ formatTooltipTime(entry.tooltip.endTimeSeconds) }}</span>
              <span>{{ t('phaseTimeline.duration') }}: {{ formatTooltipTime(entry.tooltip.durationSeconds) }}</span>
            </div>
          </template>
          <button
            class="phase-timeline-segment"
            :class="{
              'is-selected': entry.isSelected,
              'is-open': entry.isOpen,
              [`is-${entry.presentation}`]: true,
            }"
            :style="{
              left: `${entry.geometry.left}px`,
              width: `${entry.geometry.width}px`,
            }"
            type="button"
            role="option"
            :aria-selected="entry.isSelected"
            :aria-label="segmentAriaLabel(entry)"
            @click.stop="emit('selectSegment', entry.segment.id)"
            @dblclick.stop.prevent="handleSegmentDblClick(entry.segment)"
            @keydown="handleSegmentKeydown(entry.segment, $event)"
          >
            <span v-if="entry.presentation !== 'marker-only'" class="phase-timeline-segment-label">
              {{ entry.segment.phase_label.name }}
            </span>
            <span v-if="entry.presentation === 'full'" class="phase-timeline-segment-range">
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
        </el-tooltip>

        <div class="phase-timeline-playhead" :style="{ left: `${playheadLeft}px` }"></div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.phase-timeline {
  display: flex;
  flex-direction: column;
  gap: 0.62rem;
  padding: 0.78rem 0.86rem;
  border-radius: 0.72rem;
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
  padding: 0.42rem 0.62rem;
  border-radius: 0.55rem;
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
  min-height: 96px;
  border-radius: 0.62rem;
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
  overflow: hidden;
}

.phase-timeline-grid {
  position: absolute;
  inset: 0;
  border-radius: inherit;
  background:
    linear-gradient(180deg, transparent 49%, rgba(148, 163, 184, 0.08) 50%, transparent 51%);
  pointer-events: none;
}

.phase-timeline-coverage-layer {
  position: absolute;
  top: 28px;
  left: 0;
  right: 0;
  height: 44px;
  overflow: hidden;
  border-radius: 0.52rem;
  z-index: 1;
  pointer-events: none;
}

.phase-timeline-coverage-segment {
  position: absolute;
  top: 0;
  bottom: 0;
  box-sizing: border-box;
  margin: 0;
  border-radius: 0;
  background:
    linear-gradient(135deg, color-mix(in srgb, var(--phase-segment-color) 70%, #0f172a), color-mix(in srgb, var(--phase-segment-color) 42%, #0f172a));
  box-shadow: inset -1px 0 0 rgba(15, 23, 42, 0.32);
}

.phase-timeline-coverage-segment.is-open {
  background:
    repeating-linear-gradient(
      135deg,
      color-mix(in srgb, var(--phase-segment-color) 66%, #0f172a) 0,
      color-mix(in srgb, var(--phase-segment-color) 66%, #0f172a) 7px,
      color-mix(in srgb, var(--phase-segment-color) 42%, #0f172a) 7px,
      color-mix(in srgb, var(--phase-segment-color) 42%, #0f172a) 14px
    );
}

.phase-timeline-gap {
  position: absolute;
  top: 28px;
  height: 44px;
  box-sizing: border-box;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  margin: 0;
  border-radius: 0;
  color: rgba(226, 232, 240, 0.82);
  font-size: 0.78rem;
  font-weight: 700;
  background:
    repeating-linear-gradient(
      135deg,
      rgba(148, 163, 184, 0.30) 0,
      rgba(148, 163, 184, 0.30) 5px,
      rgba(30, 41, 59, 0.74) 5px,
      rgba(30, 41, 59, 0.74) 10px
    );
  z-index: 2;
}

.phase-timeline-gap.is-compact {
  color: transparent;
}

.phase-timeline-segment {
  position: absolute;
  top: 28px;
  height: 44px;
  box-sizing: border-box;
  margin: 0;
  border-radius: 0;
  border: 0;
  background: transparent;
  color: #f8fafc;
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 0.2rem;
  padding: 0.42rem 0.62rem;
  text-align: left;
  overflow: hidden;
  z-index: 3;
}

.phase-timeline-segment.is-selected {
  outline: 2px solid rgba(255, 255, 255, 0.84);
  outline-offset: -2px;
  box-shadow: inset 0 0 0 2px rgba(125, 211, 252, 0.74), 0 0 16px rgba(34, 211, 238, 0.22);
  z-index: 4;
}

.phase-timeline-segment.is-open {
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.32);
}

.phase-timeline-segment.is-label-only {
  padding: 0.36rem 0.48rem;
}

.phase-timeline-segment.is-compact {
  padding: 0.28rem 0.28rem;
  gap: 0;
}

.phase-timeline-segment.is-marker-only {
  padding: 0;
  overflow: visible;
}

.phase-timeline-segment.is-marker-only::before {
  content: '';
  position: absolute;
  top: 2px;
  bottom: 2px;
  left: 50%;
  width: 2px;
  min-width: 2px;
  transform: translateX(-50%);
  border-radius: 0;
  background: rgba(255, 255, 255, 0.58);
  box-shadow: 0 0 8px color-mix(in srgb, var(--phase-segment-color) 72%, transparent);
}

.phase-timeline-segment.is-marker-only.is-selected::before {
  width: 3px;
  background: #ffffff;
  box-shadow: 0 0 0 1px rgba(15, 23, 42, 0.78), 0 0 14px color-mix(in srgb, var(--phase-segment-color) 76%, transparent);
}

.phase-timeline-segment-label,
.phase-timeline-segment-range {
  min-width: 0;
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
  z-index: 6;
}

.phase-timeline-selected-float {
  position: absolute;
  top: 2px;
  max-width: 260px;
  transform: translateX(-50%);
  padding: 0.18rem 0.42rem;
  border-radius: 0.42rem;
  background: rgba(15, 23, 42, 0.94);
  color: #f8fafc;
  border: 1px solid rgba(125, 211, 252, 0.48);
  box-shadow: 0 10px 24px rgba(2, 6, 23, 0.24);
  pointer-events: none;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  z-index: 7;
}

.phase-timeline-tooltip {
  display: grid;
  gap: 0.18rem;
  max-width: 280px;
}

.phase-timeline-tooltip span,
.phase-timeline-tooltip strong {
  display: block;
}

@media (max-width: 900px) {
  .phase-timeline-header {
    flex-direction: column;
  }
}
</style>
