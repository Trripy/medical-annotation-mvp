export const VIDEO_PLAYBACK_RATE_OPTIONS = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 2, 3, 4] as const
export type VideoPlaybackRate = typeof VIDEO_PLAYBACK_RATE_OPTIONS[number]
export const DEFAULT_VIDEO_PLAYBACK_RATE: VideoPlaybackRate = 1
export const VIDEO_PLAYBACK_RATE_STORAGE_KEY = 'medical-annotation-video-playback-rate'

export function isSupportedPlaybackRate(value: unknown): value is VideoPlaybackRate {
  return typeof value === 'number'
    && Number.isFinite(value)
    && (VIDEO_PLAYBACK_RATE_OPTIONS as readonly number[]).includes(value)
}

export function parsePlaybackRate(value: unknown): VideoPlaybackRate | null {
  if (typeof value !== 'string' && typeof value !== 'number') {
    return null
  }
  const parsed = typeof value === 'number' ? value : Number.parseFloat(value)
  return isSupportedPlaybackRate(parsed) ? parsed : null
}

export function resolveInitialPlaybackRate(storageValue: unknown): VideoPlaybackRate {
  return parsePlaybackRate(storageValue) ?? DEFAULT_VIDEO_PLAYBACK_RATE
}

export function formatPlaybackRateLabel(rate: VideoPlaybackRate): string {
  return `${Number.isInteger(rate) ? String(rate) : String(rate)}×`
}

export function readPersistedPlaybackRate(storage: Pick<Storage, 'getItem'> | null | undefined): VideoPlaybackRate {
  try {
    return resolveInitialPlaybackRate(storage?.getItem(VIDEO_PLAYBACK_RATE_STORAGE_KEY) ?? null)
  } catch {
    return DEFAULT_VIDEO_PLAYBACK_RATE
  }
}

export function persistPlaybackRate(
  rate: VideoPlaybackRate,
  storage: Pick<Storage, 'setItem'> | null | undefined = globalThis.localStorage,
): void {
  try {
    storage?.setItem(VIDEO_PLAYBACK_RATE_STORAGE_KEY, String(rate))
  } catch {
    // Storage can be unavailable in restricted browser modes.
  }
}

export type PlaybackRateVideoLike = {
  currentTime: number
  defaultPlaybackRate: number
  paused: boolean
  playbackRate: number
  preservesPitch?: boolean
  webkitPreservesPitch?: boolean
}

export function applyPlaybackRateToVideo(video: PlaybackRateVideoLike | null | undefined, rate: VideoPlaybackRate): boolean {
  if (!video) {
    return false
  }
  const currentTime = video.currentTime
  const paused = video.paused
  try {
    video.defaultPlaybackRate = rate
    video.playbackRate = rate
    if ('preservesPitch' in video) {
      video.preservesPitch = true
    }
    if ('webkitPreservesPitch' in video) {
      video.webkitPreservesPitch = true
    }
  } catch {
    return false
  }
  if (video.currentTime !== currentTime) {
    video.currentTime = currentTime
  }
  void paused
  return true
}

export function parsePlaybackRateStorageEvent(event: Pick<StorageEvent, 'key' | 'newValue'>): VideoPlaybackRate | null {
  if (event.key !== VIDEO_PLAYBACK_RATE_STORAGE_KEY) {
    return null
  }
  return parsePlaybackRate(event.newValue)
}

export function preservePlaybackRateRouteState<T extends { query?: unknown }>(routeLike: T): T {
  return routeLike
}
