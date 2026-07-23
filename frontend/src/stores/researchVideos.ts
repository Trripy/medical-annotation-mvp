import { defineStore } from 'pinia'
import { markRaw } from 'vue'

import { apiUrl, resolveApiUrl } from '../utils/api'
import { normalizeAnnotationObject } from '../utils/polygon'
import type { AnnotationObject, ShapeType } from './annotation'

export type ResearchVideoStatus = 'processing' | 'ready' | 'failed'
export type ResearchVideoListItem = {
  id: number
  name: string
  original_filename: string
  width: number | null
  height: number | null
  fps: number | null
  frame_count: number
  duration_ms: number | null
  status: ResearchVideoStatus
  thumbnail_url: string | null
  created_at: string
  updated_at: string
}

export type ResearchVideoFrame = {
  id: number
  frame_index: number
  timestamp_ms: number
  filename: string
  width: number | null
  height: number | null
  image_url: string
}

export type ResearchVideoDetail = ResearchVideoListItem & {
  file_url: string
  frames: ResearchVideoFrame[]
  labels: ResearchVideoLabel[]
}

export type ResearchVideoWorkspaceDetail = ResearchVideoListItem & {
  file_url: string
  labels: ResearchVideoLabel[]
}

export type ResearchVideoFramesPage = {
  items: ResearchVideoFrame[]
  offset: number
  limit: number
  total: number
  has_more: boolean
}

export type ResearchVideoLabel = {
  id: number
  name: string
  color: string
  shape_type: ShapeType
  sort_order: number
  annotation_count: number
}

export type ResearchVideoAnnotation = AnnotationObject & {
  frame_id: number
  frame_index: number
  visible: boolean
}

export type ResearchVideoAnnotationPayload = {
  label_id: number
  shape_type: ShapeType
  points: number[][]
  attributes?: Record<string, unknown> | null
  visible?: boolean
}

export type ResearchVideoLabelPayload = {
  name: string
  color: string
  shape_type: ShapeType
}

function resolveStorageUrl(path: string): string {
  return resolveApiUrl(path)
}

function withCacheBuster(url: string, seed: number): string {
  const separator = url.includes('?') ? '&' : '?'
  return `${url}${separator}v=${seed}`
}

function normalizeVideo(video: ResearchVideoListItem): ResearchVideoListItem {
  return {
    ...video,
    thumbnail_url: video.thumbnail_url ? withCacheBuster(resolveStorageUrl(video.thumbnail_url), video.id) : null,
  }
}

function normalizeVideoDetail(video: ResearchVideoDetail): ResearchVideoDetail {
  return markRaw({
    ...normalizeVideo(video),
    file_url: resolveStorageUrl(video.file_url),
    frames: markRaw(video.frames.map((frame) => ({
      ...frame,
      image_url: withCacheBuster(resolveStorageUrl(frame.image_url), frame.id),
    }))),
    labels: markRaw(video.labels.slice()),
  })
}

function normalizeVideoWorkspace(video: ResearchVideoWorkspaceDetail): ResearchVideoWorkspaceDetail {
  return markRaw({
    ...normalizeVideo(video),
    file_url: resolveStorageUrl(video.file_url),
    labels: markRaw(video.labels.slice()),
  })
}

function normalizeFramesPage(page: ResearchVideoFramesPage): ResearchVideoFramesPage {
  return markRaw({
    ...page,
    items: markRaw(page.items.map((frame) => ({
      ...frame,
      image_url: withCacheBuster(resolveStorageUrl(frame.image_url), frame.id),
    }))),
  })
}

export const useResearchVideosStore = defineStore('researchVideos', {
  state: () => ({
    videos: [] as ResearchVideoListItem[],
    currentVideo: null as ResearchVideoDetail | null,
    loading: false,
    saving: false,
    error: '',
  }),
  actions: {
    async fetchVideos() {
      this.loading = true
      this.error = ''
      try {
        const response = await fetch(apiUrl('/api/research/videos'), { cache: 'no-store' })
        if (!response.ok) {
          throw new Error(`Video list request failed: ${response.status}`)
        }
        this.videos = (await response.json()).map(normalizeVideo)
      } catch (error) {
        this.error = error instanceof Error ? error.message : 'Unknown error'
      } finally {
        this.loading = false
      }
    },
    async fetchVideo(videoId: number) {
      this.loading = true
      this.error = ''
      try {
        const response = await fetch(apiUrl(`/api/research/videos/${videoId}`), { cache: 'no-store' })
        if (!response.ok) {
          throw new Error(`Video request failed: ${response.status}`)
        }
        this.currentVideo = normalizeVideoDetail(await response.json())
      } catch (error) {
        this.error = error instanceof Error ? error.message : 'Unknown error'
        this.currentVideo = null
      } finally {
        this.loading = false
      }
    },
    async fetchVideoWorkspace(videoId: number): Promise<ResearchVideoWorkspaceDetail | null> {
      this.loading = true
      this.error = ''
      try {
        const response = await fetch(apiUrl(`/api/research/videos/${videoId}/workspace`), { cache: 'no-store' })
        if (!response.ok) {
          throw new Error(`Video workspace request failed: ${response.status}`)
        }
        return normalizeVideoWorkspace(await response.json())
      } catch (error) {
        this.error = error instanceof Error ? error.message : 'Unknown error'
        return null
      } finally {
        this.loading = false
      }
    },
    async fetchVideoFramesPage(
      videoId: number,
      options: {
        offset?: number
        limit?: number
      } = {},
    ): Promise<ResearchVideoFramesPage | null> {
      const { offset = 0, limit = 500 } = options
      this.error = ''
      try {
        const searchParams = new URLSearchParams({
          offset: String(offset),
          limit: String(limit),
        })
        const response = await fetch(apiUrl(`/api/research/videos/${videoId}/frames?${searchParams.toString()}`), {
          cache: 'no-store',
        })
        if (!response.ok) {
          throw new Error(`Video frames request failed: ${response.status}`)
        }
        return normalizeFramesPage(await response.json())
      } catch (error) {
        this.error = error instanceof Error ? error.message : 'Unknown error'
        return null
      }
    },
    async uploadVideo(file: File, name?: string | null) {
      this.saving = true
      this.error = ''
      try {
        const formData = new FormData()
        formData.append('file', file)
        if (name?.trim()) {
          formData.append('name', name.trim())
        }
        const response = await fetch(apiUrl('/api/research/videos'), {
          method: 'POST',
          body: formData,
        })
        if (!response.ok) {
          const errorPayload = await response.json().catch(() => null)
          throw new Error(typeof errorPayload?.detail === 'string' ? errorPayload.detail : `Upload failed: ${response.status}`)
        }
        const created = normalizeVideo(await response.json())
        this.videos = [created, ...this.videos.filter((video) => video.id !== created.id)]
        return created
      } catch (error) {
        this.error = error instanceof Error ? error.message : 'Unknown error'
        return null
      } finally {
        this.saving = false
      }
    },
    async fetchVideoFrameAnnotations(videoId: number, frameIndex: number): Promise<ResearchVideoAnnotation[] | null> {
      this.error = ''
      try {
        const response = await fetch(apiUrl(`/api/research/videos/${videoId}/frames/${frameIndex}/annotations`), { cache: 'no-store' })
        if (!response.ok) {
          throw new Error(`Frame annotations request failed: ${response.status}`)
        }
        const payload = await response.json()
        return payload.annotations ?? []
      } catch (error) {
        this.error = error instanceof Error ? error.message : 'Unknown error'
        return null
      }
    },
    async saveVideoFrameAnnotations(
      videoId: number,
      frameIndex: number,
      annotations: ResearchVideoAnnotationPayload[],
    ): Promise<ResearchVideoAnnotation[] | null> {
      this.saving = true
      this.error = ''
      try {
        const response = await fetch(apiUrl(`/api/research/videos/${videoId}/frames/${frameIndex}/annotations`), {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ annotations }),
        })
        if (!response.ok) {
          const errorPayload = await response.json().catch(() => null)
          throw new Error(typeof errorPayload?.detail === 'string' ? errorPayload.detail : `Save failed: ${response.status}`)
        }
        return await response.json()
      } catch (error) {
        this.error = error instanceof Error ? error.message : 'Unknown error'
        return null
      } finally {
        this.saving = false
      }
    },
    async fetchVideoLabels(videoId: number): Promise<ResearchVideoLabel[] | null> {
      this.error = ''
      try {
        const response = await fetch(apiUrl(`/api/research/videos/${videoId}/labels`), { cache: 'no-store' })
        if (!response.ok) {
          throw new Error(`Labels request failed: ${response.status}`)
        }
        return await response.json()
      } catch (error) {
        this.error = error instanceof Error ? error.message : 'Unknown error'
        return null
      }
    },
    async createVideoLabel(videoId: number, payload: ResearchVideoLabelPayload): Promise<ResearchVideoLabel | null> {
      this.error = ''
      try {
        const response = await fetch(apiUrl(`/api/research/videos/${videoId}/labels`), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        })
        if (!response.ok) {
          const errorPayload = await response.json().catch(() => null)
          throw new Error(typeof errorPayload?.detail === 'string' ? errorPayload.detail : `Create label failed: ${response.status}`)
        }
        return await response.json()
      } catch (error) {
        this.error = error instanceof Error ? error.message : 'Unknown error'
        return null
      }
    },
  },
})
