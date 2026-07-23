import { computed, onBeforeUnmount, onMounted, ref, watch, type Ref } from 'vue'

import {
  applyPlaybackRateToVideo,
  DEFAULT_VIDEO_PLAYBACK_RATE,
  isSupportedPlaybackRate,
  parsePlaybackRateStorageEvent,
  persistPlaybackRate,
  readPersistedPlaybackRate,
  type VideoPlaybackRate,
} from '../utils/videoPlaybackRate.ts'

const playbackRate = ref<VideoPlaybackRate>(
  typeof window === 'undefined' ? DEFAULT_VIDEO_PLAYBACK_RATE : readPersistedPlaybackRate(window.localStorage),
)

const registeredVideos = new Set<HTMLVideoElement>()
const cleanupByVideo = new WeakMap<HTMLVideoElement, () => void>()
let storageListenerInstalled = false

function applyToVideo(video: HTMLVideoElement | null | undefined): void {
  if (!video) {
    return
  }
  applyPlaybackRateToVideo(video, playbackRate.value)
}

function applyToAllVideos(): void {
  for (const video of registeredVideos) {
    applyToVideo(video)
  }
}

export function setVideoPlaybackRate(rate: VideoPlaybackRate, options: { persist?: boolean } = {}): void {
  if (!isSupportedPlaybackRate(rate)) {
    return
  }
  playbackRate.value = rate
  if (options.persist !== false) {
    persistPlaybackRate(rate, typeof window === 'undefined' ? null : window.localStorage)
  }
  applyToAllVideos()
}

function handleStorage(event: StorageEvent): void {
  const nextRate = parsePlaybackRateStorageEvent(event)
  if (nextRate === null) {
    return
  }
  setVideoPlaybackRate(nextRate, { persist: false })
}

function ensureStorageListener(): void {
  if (storageListenerInstalled || typeof window === 'undefined') {
    return
  }
  window.addEventListener('storage', handleStorage)
  storageListenerInstalled = true
}

export function registerVideoPlaybackElement(video: HTMLVideoElement): () => void {
  const existingCleanup = cleanupByVideo.get(video)
  if (existingCleanup) {
    return existingCleanup
  }

  const reapply = () => applyToVideo(video)
  const handleRateChange = () => {
    const nativeRate = video.playbackRate
    if (nativeRate === playbackRate.value) {
      return
    }
    if (isSupportedPlaybackRate(nativeRate)) {
      setVideoPlaybackRate(nativeRate)
      return
    }
    applyToVideo(video)
  }

  registeredVideos.add(video)
  video.addEventListener('loadedmetadata', reapply)
  video.addEventListener('loadeddata', reapply)
  video.addEventListener('canplay', reapply)
  video.addEventListener('ratechange', handleRateChange)
  applyToVideo(video)

  const cleanup = () => {
    registeredVideos.delete(video)
    video.removeEventListener('loadedmetadata', reapply)
    video.removeEventListener('loadeddata', reapply)
    video.removeEventListener('canplay', reapply)
    video.removeEventListener('ratechange', handleRateChange)
    cleanupByVideo.delete(video)
  }
  cleanupByVideo.set(video, cleanup)
  return cleanup
}

export function useVideoPlaybackRate(
  videoRef?: Ref<HTMLVideoElement | null>,
  sourceRef?: Ref<string | null | undefined>,
) {
  ensureStorageListener()

  let cleanupVideo: (() => void) | null = null

  if (videoRef) {
    const stopVideoWatch = watch(
      () => videoRef.value,
      (video) => {
        cleanupVideo?.()
        cleanupVideo = video ? registerVideoPlaybackElement(video) : null
      },
      { immediate: true },
    )

    const stopSourceWatch = sourceRef
      ? watch(
        () => sourceRef.value,
        () => applyToVideo(videoRef.value),
      )
      : null

    onBeforeUnmount(() => {
      stopVideoWatch()
      stopSourceWatch?.()
      cleanupVideo?.()
      cleanupVideo = null
    })

    onMounted(() => applyToVideo(videoRef.value))
  }

  return {
    playbackRate: computed(() => playbackRate.value),
    setPlaybackRate: setVideoPlaybackRate,
    applyPlaybackRate: () => applyToVideo(videoRef?.value),
  }
}
