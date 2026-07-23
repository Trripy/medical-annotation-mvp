export function parseResearchFrameQuery(frameQuery: unknown, totalFrames: number) {
  const rawValue = Array.isArray(frameQuery) ? frameQuery[0] : frameQuery
  const parsed = Number.parseInt(String(rawValue ?? ''), 10)
  if (!Number.isInteger(parsed) || parsed < 0 || parsed >= totalFrames) {
    return 0
  }
  return parsed
}

export function toUiFrameNumber(frameIndex: number | null | undefined) {
  if (frameIndex === null || frameIndex === undefined || !Number.isFinite(frameIndex)) {
    return ''
  }
  return String(frameIndex + 1)
}

export function fromUiStartFrame(frameValue: string, frameCount: number) {
  const parsed = Number.parseInt(frameValue.trim(), 10)
  if (!Number.isInteger(parsed) || parsed < 1 || parsed > Math.max(frameCount, 1)) {
    return null
  }
  return parsed - 1
}

export function toUiInclusiveEndFrame(endFrameExclusive: number | null | undefined) {
  if (endFrameExclusive === null || endFrameExclusive === undefined || !Number.isFinite(endFrameExclusive)) {
    return ''
  }
  return String(endFrameExclusive)
}

export function fromUiInclusiveEndFrame(frameValue: string, frameCount: number) {
  const parsed = Number.parseInt(frameValue.trim(), 10)
  if (!Number.isInteger(parsed) || parsed < 1 || parsed > Math.max(frameCount, 1)) {
    return null
  }
  return parsed
}

export function buildCloseActiveEndFrame(currentFrameIndex: number, frameCount: number) {
  if (frameCount <= 0) {
    return 0
  }
  return Math.min(currentFrameIndex + 1, frameCount)
}

export function formatDurationMs(durationMs: number | null) {
  if (durationMs === null || durationMs < 0 || !Number.isFinite(durationMs)) {
    return 'Open'
  }
  const totalSeconds = Math.floor(durationMs / 1000)
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  const milliseconds = Math.floor((durationMs % 1000) / 10)
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}.${String(milliseconds).padStart(2, '0')}`
}

export function frameToTimestampMs(frameIndex: number, fps: number | null | undefined) {
  if (!Number.isFinite(fps) || !fps || fps <= 0) {
    return null
  }
  return Math.round((frameIndex / fps) * 1000)
}
