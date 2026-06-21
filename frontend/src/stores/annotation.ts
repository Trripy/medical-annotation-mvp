import { defineStore } from 'pinia'

import { apiUrl, resolveApiUrl } from '../utils/api'
import { normalizeAnnotationObject, normalizeAnnotationObjects } from '../utils/polygon'

export type Label = {
  id: number
  name: string
  color: string
  shape_type: ShapeType
  sort_order: number
  annotation_count?: number
}

export type JobImage = {
  id: number
  filename: string
  width: number | null
  height: number | null
  frame_index: number | null
  image_url: string
  thumbnail_url: string
}

export type ShapeType = 'rectangle' | 'polygon' | 'point'

export type AnnotationObject = {
  id: number | string
  image_id: number
  label_id: number
  shape_type: ShapeType
  points: number[][]
  attributes?: Record<string, unknown> | null
}

export type JobDetail = {
  id: number
  project_id: number | null
  name: string
  status: string
  task_id?: number | null
  images: JobImage[]
  labels: Label[]
  annotations: AnnotationObject[]
}

export type LabelPayload = {
  name: string
  color: string
  shape_type: ShapeType
}

export type LabelUsage = {
  label_id: number
  label_name: string
  annotation_count: number
  frame_count: number
}

export type LabelDeleteStrategy = 'reassign' | 'move_to_undefined' | 'delete_annotations'

export type LabelDeletePayload = {
  strategy?: LabelDeleteStrategy
  target_label_id?: number | null
}

export type LabelDeleteResult = {
  deleted_label_id: number
  strategy: LabelDeleteStrategy | null
  affected_annotations: number
  target_label: string | null
}

function resolveStorageUrl(path: string): string {
  return resolveApiUrl(path)
}

function normalizeJobDetail(job: JobDetail): JobDetail {
  return {
    ...job,
    images: job.images.map((image) => ({
      ...image,
      image_url: withCacheBuster(resolveStorageUrl(image.image_url), image.id),
      thumbnail_url: withCacheBuster(resolveStorageUrl(image.thumbnail_url), image.id),
    })),
    annotations: normalizeAnnotationObjects(job.annotations),
  }
}

function withCacheBuster(url: string, imageId: number): string {
  const separator = url.includes('?') ? '&' : '?'
  return `${url}${separator}v=${imageId}`
}

export const useAnnotationStore = defineStore('annotation', {
  state: () => ({
    job: null as JobDetail | null,
    loading: false,
    saving: false,
    error: '',
  }),
  actions: {
    async fetchJob(jobId: string | number) {
      this.loading = true
      this.error = ''

      try {
        const response = await fetch(apiUrl(`/api/jobs/${jobId}`), { cache: 'no-store' })

        if (!response.ok) {
          throw new Error(`Job request failed: ${response.status}`)
        }

        this.job = normalizeJobDetail(await response.json())
      } catch (error) {
        this.error = error instanceof Error ? error.message : 'Unknown error'
      } finally {
        this.loading = false
      }
    },
    async saveImageAnnotations(imageId: number, annotations: AnnotationObject[]) {
      if (!this.job) {
        return false
      }

      this.saving = true
      this.error = ''

      try {
        const normalizedAnnotations = annotations.map((annotation) => normalizeAnnotationObject(annotation))
        const response = await fetch(apiUrl(`/api/jobs/${this.job.id}/images/${imageId}/annotations`), {
          method: 'PUT',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            annotations: normalizedAnnotations.map((annotation) => ({
              label_id: annotation.label_id,
              shape_type: annotation.shape_type,
              points: annotation.points,
              attributes: annotation.attributes ?? null,
            })),
          }),
        })

        if (!response.ok) {
          throw new Error(`Save failed: ${response.status}`)
        }

        const saved = normalizeAnnotationObjects(await response.json() as AnnotationObject[])
        this.job.annotations = [
          ...this.job.annotations.filter((annotation) => annotation.image_id !== imageId),
          ...saved,
        ]
        return true
      } catch (error) {
        this.error = error instanceof Error ? error.message : 'Unknown error'
        return false
      } finally {
        this.saving = false
      }
    },
    async fetchJobLabels(jobId: string | number): Promise<Label[] | null> {
      this.error = ''

      try {
        const response = await fetch(apiUrl(`/api/jobs/${jobId}/labels`), { cache: 'no-store' })

        if (!response.ok) {
          throw new Error(`Labels request failed: ${response.status}`)
        }

        return await response.json()
      } catch (error) {
        this.error = error instanceof Error ? error.message : 'Unknown error'
        return null
      }
    },
    async createJobLabel(jobId: string | number, payload: LabelPayload): Promise<Label | null> {
      this.error = ''

      try {
        const response = await fetch(apiUrl(`/api/jobs/${jobId}/labels`), {
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
    async updateJobLabel(jobId: string | number, labelId: number, payload: LabelPayload): Promise<Label | null> {
      this.error = ''

      try {
        const response = await fetch(apiUrl(`/api/jobs/${jobId}/labels/${labelId}`), {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        })

        if (!response.ok) {
          const errorPayload = await response.json().catch(() => null)
          throw new Error(typeof errorPayload?.detail === 'string' ? errorPayload.detail : `Update label failed: ${response.status}`)
        }

        return await response.json()
      } catch (error) {
        this.error = error instanceof Error ? error.message : 'Unknown error'
        return null
      }
    },
    async getJobLabelUsage(jobId: string | number, labelId: number): Promise<LabelUsage | null> {
      this.error = ''

      try {
        const response = await fetch(apiUrl(`/api/jobs/${jobId}/labels/${labelId}/usage`), { cache: 'no-store' })

        if (!response.ok) {
          throw new Error(`Label usage request failed: ${response.status}`)
        }

        return await response.json()
      } catch (error) {
        this.error = error instanceof Error ? error.message : 'Unknown error'
        return null
      }
    },
    async deleteJobLabel(
      jobId: string | number,
      labelId: number,
      payload?: LabelDeletePayload,
    ): Promise<LabelDeleteResult | null> {
      this.error = ''

      try {
        const response = await fetch(apiUrl(`/api/jobs/${jobId}/labels/${labelId}`), {
          method: 'DELETE',
          headers: { 'Content-Type': 'application/json' },
          body: payload ? JSON.stringify(payload) : undefined,
        })

        if (!response.ok) {
          const errorPayload = await response.json().catch(() => null)
          throw new Error(typeof errorPayload?.detail === 'string' ? errorPayload.detail : `Delete label failed: ${response.status}`)
        }

        return await response.json()
      } catch (error) {
        this.error = error instanceof Error ? error.message : 'Unknown error'
        return null
      }
    },
  },
  getters: {
    imageUrl: () => resolveStorageUrl,
  },
})
