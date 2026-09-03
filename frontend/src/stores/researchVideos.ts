import { defineStore } from 'pinia'
import { markRaw } from 'vue'

import { apiUrl, resolveApiUrl } from '../utils/api'
import { normalizeAnnotationObject } from '../utils/polygon'
import type { AnnotationObject, ShapeType } from './annotation'

export type ResearchVideoStatus = 'processing' | 'ready' | 'failed'
export type ResearchVideoVisibility = 'visible' | 'hidden' | 'all'
export type ResearchVideoPhaseSummary = {
  annotation_set_count: number
  draft_count: number
  submitted_count: number
  latest_submitted_set_id: number | null
  latest_submitted_version: number | null
  latest_submitted_protocol_name: string | null
  latest_submitted_coverage_percent: number
  latest_draft_set_id: number | null
  latest_draft_version: number | null
  latest_error_count: number
  latest_warning_count: number
}
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
  source_video_id: number | null
  origin_type: string
  trim_start_frame: number | null
  trim_end_frame_exclusive: number | null
  hidden_from_video_list: boolean
  hidden_at: string | null
  hidden_reason: string | null
  notes: string | null
  phase_summary: ResearchVideoPhaseSummary
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
  z_order?: number
}

export type ResearchVideoLabelPayload = {
  name: string
  color: string
  shape_type: ShapeType
}

export type ServerVideoImportRoot = {
  id: string
  name: string
}

export type ServerVideoFileEntry = {
  name: string
  relative_path: string
  size_bytes: number
  modified_at: string | null
  extension: string
}

export type ServerVideoDirectoryEntry = {
  name: string
  relative_path: string
}

export type ServerVideoBrowseResult = {
  root_id: string
  relative_path: string
  parent_relative_path: string | null
  directories: ServerVideoDirectoryEntry[]
  videos: ServerVideoFileEntry[]
  truncated: boolean
}

export type ServerVideoScanResult = {
  root_id: string
  relative_path: string
  recursive: boolean
  video_count: number
  total_size_bytes: number
  videos: ServerVideoFileEntry[]
  unsupported_count: number
  unreadable_count: number
  truncated: boolean
}

export type ResearchVideoTrimLinkedData = {
  frame_annotation_count: number
  phase_annotation_set_count: number
  phase_segment_count: number
  skill_assessment_count: number
  skill_evidence_count: number
}

export type ResearchVideoTrimInfo = {
  video: ResearchVideoWorkspaceDetail
  linked_data: ResearchVideoTrimLinkedData
  minimum_keep_frames: number
}

export type ResearchVideoTrimPayload = {
  start_frame: number
  end_frame_exclusive: number
  display_name: string | null
  acknowledge_annotations_not_copied: boolean
  hide_source_after_success: boolean
}

export type ResearchVideoTrimResponse = {
  source_video_id: number
  trimmed_video_id: number
  status: ResearchVideoStatus
  source_video_hidden: boolean
  warnings: string[]
}

const emptyPhaseSummary = (): ResearchVideoPhaseSummary => ({
  annotation_set_count: 0,
  draft_count: 0,
  submitted_count: 0,
  latest_submitted_set_id: null,
  latest_submitted_version: null,
  latest_submitted_protocol_name: null,
  latest_submitted_coverage_percent: 0,
  latest_draft_set_id: null,
  latest_draft_version: null,
  latest_error_count: 0,
  latest_warning_count: 0,
})

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
    hidden_from_video_list: Boolean(video.hidden_from_video_list),
    hidden_at: video.hidden_at ?? null,
    hidden_reason: video.hidden_reason ?? null,
    notes: video.notes ?? null,
    phase_summary: video.phase_summary ?? emptyPhaseSummary(),
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
    visibility: 'visible' as ResearchVideoVisibility,
  }),
  actions: {
    async fetchVideos(visibility?: ResearchVideoVisibility) {
      const requestedVisibility = visibility ?? this.visibility
      this.loading = true
      this.error = ''
      this.visibility = requestedVisibility
      try {
        const params = new URLSearchParams({ visibility: requestedVisibility })
        const response = await fetch(apiUrl(`/api/research/videos?${params.toString()}`), { cache: 'no-store' })
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
    async updateVideoNotes(videoId: number, notes: string | null): Promise<boolean> {
      this.saving = true
      this.error = ''
      try {
        const response = await fetch(apiUrl(`/api/research/videos/${videoId}/notes`), {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ notes }),
        })
        if (!response.ok) {
          throw new Error(`Video notes update failed: ${response.status}`)
        }
        const payload = await response.json() as { notes: string | null; updated_at: string }
        this.videos = this.videos.map((video) => (
          video.id === videoId
            ? { ...video, notes: payload.notes, updated_at: payload.updated_at }
            : video
        ))
        if (this.currentVideo?.id === videoId) {
          this.currentVideo = { ...this.currentVideo, notes: payload.notes, updated_at: payload.updated_at }
        }
        return true
      } catch (error) {
        this.error = error instanceof Error ? error.message : 'Unknown error'
        return false
      } finally {
        this.saving = false
      }
    },
    async updateVideoVisibility(videoId: number, hidden: boolean): Promise<boolean> {
      this.saving = true
      this.error = ''
      try {
        const response = await fetch(apiUrl(`/api/research/videos/${videoId}/visibility`), {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ hidden_from_video_list: hidden }),
        })
        if (!response.ok) {
          throw new Error(`Video visibility update failed: ${response.status}`)
        }
        const payload = await response.json() as {
          hidden_from_video_list: boolean
          hidden_at: string | null
          hidden_reason: string | null
          updated_at: string
        }
        this.videos = this.videos
          .map((video) => (
            video.id === videoId
              ? {
                ...video,
                hidden_from_video_list: payload.hidden_from_video_list,
                hidden_at: payload.hidden_at,
                hidden_reason: payload.hidden_reason,
                updated_at: payload.updated_at,
              }
              : video
          ))
          .filter((video) => this.visibility === 'all' || (this.visibility === 'hidden' ? video.hidden_from_video_list : !video.hidden_from_video_list))
        return true
      } catch (error) {
        this.error = error instanceof Error ? error.message : 'Unknown error'
        return false
      } finally {
        this.saving = false
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
    async fetchVideoTrimInfo(videoId: number): Promise<ResearchVideoTrimInfo | null> {
      this.loading = true
      this.error = ''
      try {
        const response = await fetch(apiUrl(`/api/research/videos/${videoId}/trim-info`), { cache: 'no-store' })
        if (!response.ok) {
          const errorPayload = await response.json().catch(() => null)
          throw new Error(typeof errorPayload?.detail === 'string' ? errorPayload.detail : `Trim info request failed: ${response.status}`)
        }
        const payload = await response.json()
        return {
          ...payload,
          video: normalizeVideoWorkspace(payload.video),
        }
      } catch (error) {
        this.error = error instanceof Error ? error.message : 'Unknown error'
        return null
      } finally {
        this.loading = false
      }
    },
    async trimVideo(videoId: number, payload: ResearchVideoTrimPayload): Promise<ResearchVideoTrimResponse | null> {
      this.saving = true
      this.error = ''
      try {
        const response = await fetch(apiUrl(`/api/research/videos/${videoId}/trim`), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        })
        if (!response.ok) {
          const errorPayload = await response.json().catch(() => null)
          throw new Error(typeof errorPayload?.detail === 'string' ? errorPayload.detail : `Trim failed: ${response.status}`)
        }
        return await response.json()
      } catch (error) {
        this.error = error instanceof Error ? error.message : 'Unknown error'
        return null
      } finally {
        this.saving = false
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
    async fetchServerImportRoots(): Promise<{ enabled: boolean; roots: ServerVideoImportRoot[] } | null> {
      this.error = ''
      try {
        const response = await fetch(apiUrl('/api/research/server-video-import/roots'), { cache: 'no-store' })
        if (!response.ok) {
          throw new Error(`Server import roots request failed: ${response.status}`)
        }
        return await response.json()
      } catch (error) {
        this.error = error instanceof Error ? error.message : 'Unknown error'
        return null
      }
    },
    async browseServerImportDirectory(rootId: string, relativePath = ''): Promise<ServerVideoBrowseResult | null> {
      this.error = ''
      try {
        const searchParams = new URLSearchParams({ root_id: rootId, relative_path: relativePath })
        const response = await fetch(apiUrl(`/api/research/server-video-import/browse?${searchParams.toString()}`), {
          cache: 'no-store',
        })
        if (!response.ok) {
          const errorPayload = await response.json().catch(() => null)
          throw new Error(typeof errorPayload?.detail === 'string' ? errorPayload.detail : `Server directory request failed: ${response.status}`)
        }
        return await response.json()
      } catch (error) {
        this.error = error instanceof Error ? error.message : 'Unknown error'
        return null
      }
    },
    async scanServerImportFolder(rootId: string, relativePath: string, recursive: boolean): Promise<ServerVideoScanResult | null> {
      this.error = ''
      try {
        const response = await fetch(apiUrl('/api/research/server-video-import/scan-folder'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ root_id: rootId, relative_path: relativePath, recursive }),
        })
        if (!response.ok) {
          const errorPayload = await response.json().catch(() => null)
          throw new Error(typeof errorPayload?.detail === 'string' ? errorPayload.detail : `Server folder scan failed: ${response.status}`)
        }
        return await response.json()
      } catch (error) {
        this.error = error instanceof Error ? error.message : 'Unknown error'
        return null
      }
    },
    async importServerVideo(rootId: string, relativePath: string, displayName?: string | null) {
      this.saving = true
      this.error = ''
      try {
        const response = await fetch(apiUrl('/api/research/server-video-import/file'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            root_id: rootId,
            relative_path: relativePath,
            display_name: displayName?.trim() || null,
          }),
        })
        if (!response.ok) {
          const errorPayload = await response.json().catch(() => null)
          throw new Error(typeof errorPayload?.detail === 'string' ? errorPayload.detail : `Server video import failed: ${response.status}`)
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
