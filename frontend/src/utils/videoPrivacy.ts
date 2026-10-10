import type { SupportedLocale } from './locale'

export type ResearchVideoNameSource = {
  id: number | string
  name?: string | null
  display_name?: string | null
  original_filename?: string | null
}

export type ResearchVideoFrameNameSource = {
  frame_index: number
  filename?: string | null
}

export function getResearchVideoAlias(videoId: number | string, locale: string | SupportedLocale): string {
  return String(locale).startsWith('zh') ? `视频 #${videoId}` : `Video #${videoId}`
}

export function getResearchVideoDisplayName(
  video: ResearchVideoNameSource | null | undefined,
  hidden: boolean,
  locale: string | SupportedLocale,
  fallback = '',
): string {
  if (!video) return fallback
  if (hidden) return getResearchVideoAlias(video.id, locale)
  return video.display_name || video.name || video.original_filename || fallback || getResearchVideoAlias(video.id, locale)
}

export function getResearchVideoFrameDisplayName(
  frame: ResearchVideoFrameNameSource | null | undefined,
  hidden: boolean,
  locale: string | SupportedLocale,
): string {
  if (!frame) return ''
  if (hidden) {
    const oneBasedFrame = Number.isFinite(frame.frame_index) ? frame.frame_index + 1 : ''
    return String(locale).startsWith('zh') ? `第 ${oneBasedFrame} 帧` : `Frame #${oneBasedFrame}`
  }
  return frame.filename || getResearchVideoFrameDisplayName(frame, true, locale)
}

export function getRelatedResearchVideoDisplayName(
  videoId: number | string | null | undefined,
  rawName: string | null | undefined,
  hidden: boolean,
  locale: string | SupportedLocale,
  fallback = '',
): string {
  if (hidden && videoId !== null && videoId !== undefined) {
    return getResearchVideoAlias(videoId, locale)
  }
  return rawName || (videoId !== null && videoId !== undefined ? String(videoId) : fallback)
}

export function containsSensitiveVideoName(text: string, sensitiveTokens: readonly string[]): boolean {
  return sensitiveTokens.some((token) => token.length > 0 && text.includes(token))
}
