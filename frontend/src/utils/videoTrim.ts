export type TrimRange = {
  startFrame: number
  endFrameExclusive: number
}

export type UiTrimRange = {
  startFrameInclusiveOneBased: number
  endFrameInclusiveOneBased: number
}

export type TrimTimelineGeometry = {
  startPercent: number
  endPercent: number
  selectionWidthPercent: number
  playheadPercent: number
}

function clampPercent(value: number): number {
  if (!Number.isFinite(value)) {
    return 0
  }
  return Math.max(0, Math.min(100, value))
}

export function getTimelineGeometry(options: {
  frameCount: number
  startFrame: number
  endFrameExclusive: number
  currentFrame: number
}): TrimTimelineGeometry {
  const frameCount = Math.max(0, Math.trunc(options.frameCount))
  if (frameCount <= 0) {
    return {
      startPercent: 0,
      endPercent: 0,
      selectionWidthPercent: 0,
      playheadPercent: 0,
    }
  }
  const startPercent = clampPercent((options.startFrame / frameCount) * 100)
  const endPercent = clampPercent((options.endFrameExclusive / frameCount) * 100)
  return {
    startPercent,
    endPercent,
    selectionWidthPercent: Math.max(0, endPercent - startPercent),
    playheadPercent: clampPercent((options.currentFrame / frameCount) * 100),
  }
}

export function backendRangeToUi(range: TrimRange): UiTrimRange {
  return {
    startFrameInclusiveOneBased: range.startFrame + 1,
    endFrameInclusiveOneBased: range.endFrameExclusive,
  }
}

export function uiRangeToBackend(uiRange: UiTrimRange): TrimRange {
  return {
    startFrame: Math.max(0, Math.trunc(uiRange.startFrameInclusiveOneBased) - 1),
    endFrameExclusive: Math.max(0, Math.trunc(uiRange.endFrameInclusiveOneBased)),
  }
}

export function clampTrimRange(range: TrimRange, frameCount: number, minimumFrames: number): TrimRange {
  const total = Math.max(0, Math.trunc(frameCount))
  const minimum = Math.max(1, Math.trunc(minimumFrames))
  if (total <= minimum) {
    return { startFrame: 0, endFrameExclusive: total }
  }
  let startFrame = Math.max(0, Math.min(Math.trunc(range.startFrame), total - minimum))
  let endFrameExclusive = Math.max(startFrame + minimum, Math.min(Math.trunc(range.endFrameExclusive), total))
  if (endFrameExclusive - startFrame < minimum) {
    startFrame = Math.max(0, endFrameExclusive - minimum)
  }
  return { startFrame, endFrameExclusive }
}

export function frameToSeconds(frameIndex: number, fps: number | null | undefined): number {
  return fps && fps > 0 ? frameIndex / fps : 0
}

export function secondsToFrame(seconds: number, fps: number | null | undefined, frameCount: number): number {
  if (!fps || fps <= 0 || !Number.isFinite(seconds)) {
    return 0
  }
  return Math.max(0, Math.min(frameCount, Math.round(seconds * fps)))
}

export function trimOutputFrameCount(range: TrimRange): number {
  return Math.max(0, range.endFrameExclusive - range.startFrame)
}

export function isFullRange(range: TrimRange, frameCount: number): boolean {
  return range.startFrame === 0 && range.endFrameExclusive === frameCount
}

export function isRangeTooShort(range: TrimRange, minimumFrames: number): boolean {
  return trimOutputFrameCount(range) < minimumFrames
}

export function defaultTrimmedName(sourceName: string): string {
  const withoutQuery = sourceName.split(/[?#]/)[0] || 'video'
  const basename = withoutQuery.split(/[\\/]/).pop() || 'video'
  const stem = basename.replace(/\.[^.]*$/, '') || 'video'
  return `${stem}_trimmed.mp4`
}

export function sanitizeTrimOutputName(name: string, fallbackSourceName: string): string {
  const trimmed = (name || defaultTrimmedName(fallbackSourceName)).trim()
  const basename = trimmed.replace(/\\/g, '/').split('/').pop() || defaultTrimmedName(fallbackSourceName)
  const safe = basename.replace(/[<>:"|?*\u0000-\u001f]/g, '_').slice(0, 255)
  if (!safe.toLowerCase().endsWith('.mp4')) {
    return `${safe.replace(/\.[^.]*$/, '') || 'trimmed_video'}.mp4`
  }
  return safe
}

export function formatTrimTimestamp(seconds: number): string {
  const safeSeconds = Math.max(0, Number.isFinite(seconds) ? seconds : 0)
  const hours = Math.floor(safeSeconds / 3600)
  const minutes = Math.floor((safeSeconds % 3600) / 60)
  const wholeSeconds = Math.floor(safeSeconds % 60)
  const millis = Math.round((safeSeconds - Math.floor(safeSeconds)) * 1000)
  return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(wholeSeconds).padStart(2, '0')}.${String(millis).padStart(3, '0')}`
}

export function parseTrimTimestamp(value: string): number | null {
  const match = value.trim().match(/^(?:(\d+):)?(\d{1,2}):(\d{1,2})(?:\.(\d{1,3}))?$/)
  if (!match) {
    const numeric = Number.parseFloat(value)
    return Number.isFinite(numeric) && numeric >= 0 ? numeric : null
  }
  const hours = Number.parseInt(match[1] ?? '0', 10)
  const minutes = Number.parseInt(match[2], 10)
  const seconds = Number.parseInt(match[3], 10)
  const millis = Number.parseInt((match[4] ?? '').padEnd(3, '0') || '0', 10)
  return hours * 3600 + minutes * 60 + seconds + millis / 1000
}

export function buildTrimPayload(
  range: TrimRange,
  displayName: string,
  acknowledgeAnnotationsNotCopied: boolean,
) {
  return {
    start_frame: range.startFrame,
    end_frame_exclusive: range.endFrameExclusive,
    display_name: displayName,
    acknowledge_annotations_not_copied: acknowledgeAnnotationsNotCopied,
  }
}
