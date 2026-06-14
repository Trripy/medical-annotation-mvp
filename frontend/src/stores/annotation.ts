import { defineStore } from 'pinia'

import { apiUrl, resolveApiUrl } from '../utils/api'

export type Label = {
  id: number
  name: string
  color: string
  shape_type: ShapeType
  sort_order: number
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
        const response = await fetch(apiUrl(`/api/jobs/${this.job.id}/images/${imageId}/annotations`), {
          method: 'PUT',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            annotations: annotations.map((annotation) => ({
              label_id: annotation.label_id,
              shape_type: annotation.shape_type,
              points: annotation.points,
            })),
          }),
        })

        if (!response.ok) {
          throw new Error(`Save failed: ${response.status}`)
        }

        const saved: AnnotationObject[] = await response.json()
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
  },
  getters: {
    imageUrl: () => resolveStorageUrl,
  },
})
