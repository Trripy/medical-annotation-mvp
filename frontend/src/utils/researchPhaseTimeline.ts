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

export type VisibleFrameRange = {
  startFrame: number
  endFrameExclusive: number
}

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
    width: Math.max(1, right - left),
    right,
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
