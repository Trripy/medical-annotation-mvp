import type { ResearchPhaseSegment } from '../types/researchPhase'

const DEFAULT_FRAMES_PER_PIXEL = 4
const MIN_TIMELINE_WIDTH = 320

export type TimelineGeometryInput = {
  frameCount: number
  framesPerPixel: number
}

export type TimelineSegmentGeometry = {
  left: number
  width: number
  right: number
}

export type TimelineSegmentEdges = {
  leftPx: number
  rightPx: number
  trueWidthPx: number
  needsSubpixelMarker: boolean
}

export type VisibleFrameRange = {
  startFrame: number
  endFrameExclusive: number
}

export type PhaseSegmentPresentation = 'full' | 'label-only' | 'compact' | 'marker-only'

export type PhaseSegmentTooltip = {
  name: string
  startFrameOneBased: number
  endFrameInclusiveOneBased: number
  durationFrames: number
  startTimeSeconds: number
  endTimeSeconds: number
  durationSeconds: number
}

export type FocusedVisibleRange = {
  startFrame: number
  endFrameExclusive: number
  framesPerPixel: number
}

export type PhaseCoverageGap = {
  startFrame: number
  endFrameExclusive: number
  durationFrames: number
}

export type PhaseGapAtFrame = {
  gapStartFrame: number
  gapEndFrameExclusive: number
  previousSegmentId: number | null
  nextSegmentId: number | null
  containsTargetFrame: boolean
}

export type NewPhaseStartResolution = {
  startFrame: number | null
  source: 'pending-next-frame' | 'current-frame'
  conflict: 'none' | 'out-of-bounds' | 'occupied-start' | 'occupied-inside'
  occupiedSegmentId: number | null
  reason: 'ok' | 'no-next-frame' | 'next-frame-already-annotated' | 'next-frame-occupied'
}

export type PhaseNextStartHint = {
  annotationSetId: number
  startFrame: number
  sourceSegmentId: number
  sourceEndFrameExclusive: number
  annotationSetRevision: number
  closedAtPlayheadFrame: number
}

export const MIN_VISIBLE_SEGMENT_PX = 2
export const SHORT_SEGMENT_HIT_RADIUS_PX = 6
export const TIMELINE_PRESENTATION_FULL_PX = 120
export const TIMELINE_PRESENTATION_LABEL_ONLY_PX = 64
export const TIMELINE_PRESENTATION_COMPACT_PX = 28

export function clampFrame(frame: number, frameCount: number) {
  if (!Number.isFinite(frameCount) || frameCount <= 0) {
    return 0
  }
  if (!Number.isFinite(frame)) {
    return 0
  }
  return Math.max(0, Math.min(Math.round(frame), frameCount))
}

export function normalizeFramesPerPixel(framesPerPixel: number) {
  if (!Number.isFinite(framesPerPixel) || framesPerPixel <= 0) {
    return DEFAULT_FRAMES_PER_PIXEL
  }
  return framesPerPixel
}

export function frameToPixel(frame: number, input: TimelineGeometryInput) {
  if (input.frameCount <= 0) {
    return 0
  }
  const boundedFrame = clampFrame(frame, input.frameCount)
  return boundedFrame / normalizeFramesPerPixel(input.framesPerPixel)
}

export function pixelToFrame(pixel: number, input: TimelineGeometryInput) {
  if (input.frameCount <= 0) {
    return 0
  }
  if (!Number.isFinite(pixel)) {
    return 0
  }
  const nextFrame = pixel * normalizeFramesPerPixel(input.framesPerPixel)
  return clampFrame(nextFrame, input.frameCount)
}

export function calculateTimelineWidth(input: TimelineGeometryInput) {
  if (input.frameCount <= 0) {
    return MIN_TIMELINE_WIDTH
  }
  return Math.max(MIN_TIMELINE_WIDTH, Math.ceil(input.frameCount / normalizeFramesPerPixel(input.framesPerPixel)))
}

export function calculateSegmentGeometry(
  segment: Pick<ResearchPhaseSegment, 'start_frame' | 'end_frame_exclusive'>,
  input: TimelineGeometryInput,
): TimelineSegmentGeometry {
  const startFrame = clampFrame(segment.start_frame, input.frameCount)
  const endFrame = clampFrame(segment.end_frame_exclusive ?? input.frameCount, input.frameCount)
  const left = frameToPixel(startFrame, input)
  const right = frameToPixel(Math.max(startFrame, endFrame), input)
  return {
    left,
    width: Math.max(0, right - left),
    right,
  }
}

export function calculatePhaseSegmentEdges(
  segment: Pick<ResearchPhaseSegment, 'start_frame' | 'end_frame_exclusive'>,
  input: TimelineGeometryInput,
): TimelineSegmentEdges {
  const geometry = calculateSegmentGeometry(segment, input)
  const timelineWidth = calculateTimelineWidth(input)
  return {
    leftPx: geometry.left,
    rightPx: Math.max(0, timelineWidth - geometry.right),
    trueWidthPx: geometry.width,
    needsSubpixelMarker: geometry.width > 0 && geometry.width < MIN_VISIBLE_SEGMENT_PX,
  }
}

export function getClippedPhaseSegmentGeometry(
  segment: Pick<ResearchPhaseSegment, 'start_frame' | 'end_frame_exclusive'>,
  window: VisibleFrameRange,
): {
  leftPercent: number
  rightPercent: number
  widthPercent: number
  clippedStartFrame: number
  clippedEndFrameExclusive: number
  visible: boolean
} {
  const visibleFrameCount = window.endFrameExclusive - window.startFrame
  const segmentEnd = segment.end_frame_exclusive ?? window.endFrameExclusive
  const clippedStartFrame = Math.max(segment.start_frame, window.startFrame)
  const clippedEndFrameExclusive = Math.min(segmentEnd, window.endFrameExclusive)
  if (visibleFrameCount <= 0 || clippedEndFrameExclusive <= clippedStartFrame) {
    return {
      leftPercent: 0,
      rightPercent: 0,
      widthPercent: 0,
      clippedStartFrame,
      clippedEndFrameExclusive,
      visible: false,
    }
  }
  const leftPercent = ((clippedStartFrame - window.startFrame) / visibleFrameCount) * 100
  const rightPercent = ((clippedEndFrameExclusive - window.startFrame) / visibleFrameCount) * 100
  return {
    leftPercent,
    rightPercent,
    widthPercent: rightPercent - leftPercent,
    clippedStartFrame,
    clippedEndFrameExclusive,
    visible: true,
  }
}

export function getPhaseSegmentPixelWidth(geometry: Pick<TimelineSegmentGeometry, 'width'>): number {
  return Math.max(0, geometry.width)
}

export function getPhaseSegmentPresentation(widthPx: number): PhaseSegmentPresentation {
  if (widthPx >= TIMELINE_PRESENTATION_FULL_PX) {
    return 'full'
  }
  if (widthPx >= TIMELINE_PRESENTATION_LABEL_ONLY_PX) {
    return 'label-only'
  }
  if (widthPx >= TIMELINE_PRESENTATION_COMPACT_PX) {
    return 'compact'
  }
  return 'marker-only'
}

export function getPhaseSegmentTooltip(
  segment: Pick<ResearchPhaseSegment, 'start_frame' | 'end_frame_exclusive'> & {
    phase_label: Pick<ResearchPhaseSegment['phase_label'], 'name'>
  },
  frameCount: number,
  fps: number | null | undefined,
): PhaseSegmentTooltip {
  const endFrameExclusive = segment.end_frame_exclusive ?? frameCount
  const durationFrames = Math.max(0, endFrameExclusive - segment.start_frame)
  const startTimeSeconds = fps && fps > 0 ? segment.start_frame / fps : 0
  const endTimeSeconds = fps && fps > 0 ? endFrameExclusive / fps : 0
  return {
    name: segment.phase_label.name,
    startFrameOneBased: segment.start_frame + 1,
    endFrameInclusiveOneBased: endFrameExclusive,
    durationFrames,
    startTimeSeconds,
    endTimeSeconds,
    durationSeconds: Math.max(0, endTimeSeconds - startTimeSeconds),
  }
}

export function findSegmentAtFrame(
  segments: readonly ResearchPhaseSegment[],
  frameIndex: number,
): ResearchPhaseSegment | null {
  for (const segment of segments) {
    const endFrameExclusive = segment.end_frame_exclusive ?? Number.POSITIVE_INFINITY
    if (segment.start_frame <= frameIndex && frameIndex < endFrameExclusive) {
      return segment
    }
  }
  return null
}

export function hitTestPhaseSegment(
  pointerX: number,
  trackWidth: number,
  visibleStartFrame: number,
  visibleEndFrameExclusive: number,
  segments: readonly ResearchPhaseSegment[],
): ResearchPhaseSegment | null {
  const visibleFrameCount = visibleEndFrameExclusive - visibleStartFrame
  if (trackWidth <= 0 || visibleFrameCount <= 0 || !Number.isFinite(pointerX)) {
    return null
  }
  const clampedX = Math.max(0, Math.min(pointerX, trackWidth))
  const targetFrame = visibleStartFrame + (clampedX / trackWidth) * visibleFrameCount
  const containing = segments.find((segment) => {
    const endFrameExclusive = segment.end_frame_exclusive ?? visibleEndFrameExclusive
    return segment.start_frame <= targetFrame && targetFrame < endFrameExclusive
  })
  if (containing) {
    return containing
  }

  const candidates = segments
    .map((segment) => {
      const endFrameExclusive = segment.end_frame_exclusive ?? visibleEndFrameExclusive
      const geometry = getClippedPhaseSegmentGeometry(segment, {
        startFrame: visibleStartFrame,
        endFrameExclusive: visibleEndFrameExclusive,
      })
      if (!geometry.visible) {
        return null
      }
      const leftPx = (geometry.leftPercent / 100) * trackWidth
      const rightPx = (geometry.rightPercent / 100) * trackWidth
      const centerPx = (leftPx + rightPx) / 2
      const distancePx = Math.abs(clampedX - centerPx)
      if (distancePx > SHORT_SEGMENT_HIT_RADIUS_PX) {
        return null
      }
      return {
        segment,
        distancePx,
        durationFrames: Math.max(0, endFrameExclusive - segment.start_frame),
      }
    })
    .filter((candidate): candidate is { segment: ResearchPhaseSegment; distancePx: number; durationFrames: number } => Boolean(candidate))
    .sort((left, right) =>
      left.distancePx - right.distancePx ||
      left.durationFrames - right.durationFrames ||
      left.segment.start_frame - right.segment.start_frame ||
      left.segment.id - right.segment.id,
    )
  return candidates[0]?.segment ?? null
}

export function calculateVisibleFrameRange(
  scrollLeft: number,
  viewportWidth: number,
  input: TimelineGeometryInput,
): VisibleFrameRange {
  if (input.frameCount <= 0 || viewportWidth <= 0) {
    return {
      startFrame: 0,
      endFrameExclusive: 0,
    }
  }

  const clampedScrollLeft = Math.max(0, scrollLeft)
  const startFrame = pixelToFrame(clampedScrollLeft, input)
  const endFrameExclusive = Math.max(
    startFrame,
    pixelToFrame(clampedScrollLeft + viewportWidth, input),
  )

  return {
    startFrame,
    endFrameExclusive,
  }
}

export function getFocusedVisibleRange(options: {
  segment: Pick<ResearchPhaseSegment, 'start_frame' | 'end_frame_exclusive'>
  frameCount: number
  fps: number | null | undefined
  viewportWidth: number
}): FocusedVisibleRange {
  const frameCount = Math.max(0, Math.trunc(options.frameCount))
  const viewportWidth = Math.max(1, Math.trunc(options.viewportWidth))
  if (frameCount <= 0) {
    return { startFrame: 0, endFrameExclusive: 0, framesPerPixel: DEFAULT_FRAMES_PER_PIXEL }
  }
  const segmentEnd = clampFrame(options.segment.end_frame_exclusive ?? frameCount, frameCount)
  const segmentStart = clampFrame(options.segment.start_frame, frameCount)
  const segmentLength = Math.max(1, segmentEnd - segmentStart)
  const fpsMinimum = options.fps && options.fps > 0 ? Math.ceil(options.fps * 5) : 0
  const minimumWindowFrames = Math.min(frameCount, Math.max(fpsMinimum, 100))
  const desiredWindowFrames = Math.min(frameCount, Math.max(minimumWindowFrames, segmentLength * 4))
  const center = segmentStart + (segmentLength / 2)
  let startFrame = Math.round(center - (desiredWindowFrames / 2))
  startFrame = Math.max(0, Math.min(startFrame, Math.max(0, frameCount - desiredWindowFrames)))
  const endFrameExclusive = Math.min(frameCount, startFrame + desiredWindowFrames)
  return {
    startFrame,
    endFrameExclusive,
    framesPerPixel: normalizeFramesPerPixel((endFrameExclusive - startFrame) / viewportWidth),
  }
}

export function getTimelinePlayheadPercent(
  currentFrame: number,
  visibleStartFrame: number,
  visibleEndFrameExclusive: number,
): number {
  const visibleFrameCount = visibleEndFrameExclusive - visibleStartFrame
  if (visibleFrameCount <= 0 || !Number.isFinite(currentFrame)) {
    return 0
  }
  return Math.max(0, Math.min(100, ((currentFrame - visibleStartFrame) / visibleFrameCount) * 100))
}

export function toUiStartFrame(startFrame: number): number {
  return startFrame + 1
}

export function toUiEndFrameInclusive(endFrameExclusive: number | null | undefined, frameCount: number): number {
  return endFrameExclusive ?? frameCount
}

export function toApiStartFrame(uiStartFrame: number): number {
  return Math.max(0, uiStartFrame - 1)
}

export function toApiEndFrameExclusive(uiEndFrameInclusive: number): number {
  return Math.max(0, uiEndFrameInclusive)
}

export function getSegmentFrameCount(segment: Pick<ResearchPhaseSegment, 'start_frame' | 'end_frame_exclusive'>, frameCount: number): number {
  return Math.max(0, (segment.end_frame_exclusive ?? frameCount) - segment.start_frame)
}

export function segmentsOverlap(
  left: Pick<ResearchPhaseSegment, 'start_frame' | 'end_frame_exclusive'>,
  right: Pick<ResearchPhaseSegment, 'start_frame' | 'end_frame_exclusive'>,
  frameCount = Number.POSITIVE_INFINITY,
): boolean {
  const leftEnd = left.end_frame_exclusive ?? frameCount
  const rightEnd = right.end_frame_exclusive ?? frameCount
  return left.start_frame < rightEnd && right.start_frame < leftEnd
}

export function segmentsAreAdjacent(
  left: Pick<ResearchPhaseSegment, 'start_frame' | 'end_frame_exclusive'>,
  right: Pick<ResearchPhaseSegment, 'start_frame' | 'end_frame_exclusive'>,
): boolean {
  return left.end_frame_exclusive !== null && left.end_frame_exclusive !== undefined && left.end_frame_exclusive === right.start_frame
}

export function getVisiblePhaseCoverageGaps(
  window: VisibleFrameRange,
  segments: readonly Pick<ResearchPhaseSegment, 'start_frame' | 'end_frame_exclusive'>[],
): PhaseCoverageGap[] {
  if (window.endFrameExclusive <= window.startFrame) {
    return []
  }
  const clippedIntervals = segments
    .map((segment) => ({
      startFrame: Math.max(window.startFrame, segment.start_frame),
      endFrameExclusive: Math.min(window.endFrameExclusive, segment.end_frame_exclusive ?? window.endFrameExclusive),
    }))
    .filter((interval) => interval.endFrameExclusive > interval.startFrame)
    .sort((left, right) => left.startFrame - right.startFrame || left.endFrameExclusive - right.endFrameExclusive)

  const gaps: PhaseCoverageGap[] = []
  let cursor = window.startFrame
  for (const interval of clippedIntervals) {
    if (interval.startFrame > cursor) {
      gaps.push({
        startFrame: cursor,
        endFrameExclusive: interval.startFrame,
        durationFrames: interval.startFrame - cursor,
      })
    }
    cursor = Math.max(cursor, interval.endFrameExclusive)
  }
  if (cursor < window.endFrameExclusive) {
    gaps.push({
      startFrame: cursor,
      endFrameExclusive: window.endFrameExclusive,
      durationFrames: window.endFrameExclusive - cursor,
    })
  }
  return gaps
}

export function findPhaseGapAtFrame(
  segments: readonly Pick<ResearchPhaseSegment, 'id' | 'start_frame' | 'end_frame_exclusive'>[],
  targetFrame: number,
  videoFrameCount: number,
  ignoreSegmentId: number | null = null,
): PhaseGapAtFrame | null {
  if (!Number.isFinite(targetFrame) || !Number.isFinite(videoFrameCount) || videoFrameCount <= 0) {
    return null
  }
  const boundedTarget = Math.max(0, Math.min(Math.trunc(targetFrame), videoFrameCount - 1))
  const sortedSegments = segments
    .filter((segment) => segment.id !== ignoreSegmentId)
    .map((segment) => ({
      id: segment.id,
      startFrame: clampFrame(segment.start_frame, videoFrameCount),
      endFrameExclusive: clampFrame(segment.end_frame_exclusive ?? videoFrameCount, videoFrameCount),
    }))
    .filter((segment) => segment.endFrameExclusive > segment.startFrame)
    .sort((left, right) => left.startFrame - right.startFrame || left.endFrameExclusive - right.endFrameExclusive || left.id - right.id)

  let cursor = 0
  let previousSegmentId: number | null = null
  for (const segment of sortedSegments) {
    if (boundedTarget >= segment.startFrame && boundedTarget < segment.endFrameExclusive) {
      return null
    }
    if (boundedTarget >= cursor && boundedTarget < segment.startFrame) {
      return {
        gapStartFrame: cursor,
        gapEndFrameExclusive: segment.startFrame,
        previousSegmentId,
        nextSegmentId: segment.id,
        containsTargetFrame: true,
      }
    }
    if (segment.endFrameExclusive > cursor) {
      cursor = segment.endFrameExclusive
      previousSegmentId = segment.id
    }
  }

  if (boundedTarget >= cursor && boundedTarget < videoFrameCount) {
    return {
      gapStartFrame: cursor,
      gapEndFrameExclusive: videoFrameCount,
      previousSegmentId,
      nextSegmentId: null,
      containsTargetFrame: true,
    }
  }

  return null
}

export function resolveNewPhaseStartFrame(options: {
  currentFrame: number
  pendingNextStartFrame: number | null
  existingSegments: readonly ResearchPhaseSegment[]
  videoFrameCount: number
}): NewPhaseStartResolution {
  const hasPending = options.pendingNextStartFrame !== null && Number.isFinite(options.pendingNextStartFrame)
  const requestedFrame = hasPending ? Number(options.pendingNextStartFrame) : options.currentFrame
  const source = hasPending ? 'pending-next-frame' : 'current-frame'
  if (requestedFrame < 0 || requestedFrame >= options.videoFrameCount) {
    return {
      startFrame: null,
      source,
      conflict: 'out-of-bounds',
      occupiedSegmentId: null,
      reason: 'no-next-frame',
    }
  }
  const occupiedSegment = findSegmentAtFrame(options.existingSegments, requestedFrame)
  if (occupiedSegment) {
    return {
      startFrame: null,
      source,
      conflict: occupiedSegment.start_frame === requestedFrame ? 'occupied-start' : 'occupied-inside',
      occupiedSegmentId: occupiedSegment.id,
      reason: occupiedSegment.start_frame === requestedFrame ? 'next-frame-already-annotated' : 'next-frame-occupied',
    }
  }
  return {
    startFrame: requestedFrame,
    source,
    conflict: 'none',
    occupiedSegmentId: null,
    reason: 'ok',
  }
}

export function getValidPhaseNextStartHint(
  hint: PhaseNextStartHint | null,
  context: {
    annotationSetId: number | null | undefined
    annotationSetRevision: number | null | undefined
    currentFrame: number
    videoFrameCount: number
    existingSegments: readonly Pick<ResearchPhaseSegment, 'id' | 'end_frame_exclusive'>[]
  },
): PhaseNextStartHint | null {
  if (!hint || !Number.isFinite(context.videoFrameCount) || context.videoFrameCount <= 0) {
    return null
  }
  if (context.annotationSetId !== hint.annotationSetId || context.annotationSetRevision !== hint.annotationSetRevision) {
    return null
  }
  if (context.currentFrame !== hint.closedAtPlayheadFrame) {
    return null
  }
  if (hint.startFrame !== hint.sourceEndFrameExclusive || hint.startFrame < 0 || hint.startFrame >= context.videoFrameCount) {
    return null
  }
  const sourceSegment = context.existingSegments.find((segment) => segment.id === hint.sourceSegmentId)
  if (!sourceSegment || sourceSegment.end_frame_exclusive !== hint.sourceEndFrameExclusive) {
    return null
  }
  return hint
}
