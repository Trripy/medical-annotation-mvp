import { defineStore } from 'pinia'

import { apiUrl, resolveApiUrl } from '../utils/api'

export type JobCard = {
  id: number
  project_id: number | null
  project_name: string | null
  name: string
  status: string
  task_id?: number | null
  frames: number
  annotated_images_count: number
  thumbnail_url: string | null
}

export type ProjectCard = {
  id: number
  name: string
  job_count: number
  frame_count: number
  thumbnail_url: string | null
}

export type JobExportFormat = 'labelme' | 'overlay' | 'indexed-mask' | 'color-mask'
export type JobExportScope = 'all' | 'annotated_only'
export type JobImportFormat = 'auto' | 'labelme' | 'coco' | 'cvat' | 'yolo' | 'mask' | 'voc' | 'via' | 'supervisely'
export type JobImportMode = 'append' | 'replace_matched_images' | 'replace_all_job'
export type MissingLabelPolicy = 'auto_create' | 'skip'
export type JobImportReport = {
  job_id: number
  format_detected: string
  matched_images: number
  unmatched_items: number
  created_annotations: number
  created_labels: string[]
  created_label_details?: Array<{
    name: string
    color: string
    requested_color: string | null
    color_changed: boolean
    reason: string | null
  }>
  reassigned_conflicting_colors?: number
  skipped_items: Array<{ source: string; reason: string }>
  errors: string[]
}

const exportConfigs: Record<JobExportFormat, { endpoint: string; filenameSuffix: string }> = {
  labelme: {
    endpoint: 'labelme',
    filenameSuffix: 'labelme',
  },
  overlay: {
    endpoint: 'overlay',
    filenameSuffix: 'overlay',
  },
  'indexed-mask': {
    endpoint: 'indexed-mask',
    filenameSuffix: 'mask_indexed',
  },
  'color-mask': {
    endpoint: 'color-mask',
    filenameSuffix: 'mask_color',
  },
}

function resolveThumbnailUrl(path: string | null): string {
  return resolveApiUrl(path)
}

function sanitizeFilename(name: string | null | undefined, fallback: string): string {
  const rawName = (name ?? '').trim()
  if (!rawName) {
    return fallback
  }

  const normalizedCharacters = Array.from(rawName, (character) => {
    if (/[/\\:*?"<>|]/.test(character)) {
      return '_'
    }
    if (/\s/.test(character)) {
      return '_'
    }
    return character
  })

  const normalized = normalizedCharacters.join('')
    .replace(/_+/g, '_')
    .replace(/^[_\.]+|[_\.]+$/g, '')

  return normalized || fallback
}

function buildExportFilename(
  job: Pick<JobCard, 'id' | 'name'>,
  format: JobExportFormat,
  scope: JobExportScope,
): string {
  const config = exportConfigs[format]
  const safeJobName = sanitizeFilename(job.name, `job_${job.id}`)
  const scopeSuffix = scope === 'annotated_only' ? '_annotated_only' : ''
  return `${safeJobName}_${config.filenameSuffix}${scopeSuffix}.zip`
}

function parseContentDispositionFilename(contentDisposition: string | null): string | null {
  if (!contentDisposition) {
    return null
  }

  const encodedMatch = contentDisposition.match(/filename\*\s*=\s*([^;]+)/i)
  if (encodedMatch) {
    const encodedValue = encodedMatch[1].trim().replace(/^"|"$/g, '')
    const normalizedValue = encodedValue.replace(/^UTF-8''/i, '')
    try {
      return decodeURIComponent(normalizedValue)
    } catch {
      return normalizedValue
    }
  }

  const basicMatch = contentDisposition.match(/filename\s*=\s*([^;]+)/i)
  if (!basicMatch) {
    return null
  }

  return basicMatch[1].trim().replace(/^"|"$/g, '')
}

export const useJobsStore = defineStore('jobs', {
  state: () => ({
    projects: [] as ProjectCard[],
    jobs: [] as JobCard[],
    loading: false,
    exportingJobIds: [] as number[],
    error: '',
  }),
  actions: {
    async fetchProjects() {
      this.loading = true
      this.error = ''

      try {
        const response = await fetch(apiUrl('/api/projects'))

        if (!response.ok) {
          throw new Error(`Projects request failed: ${response.status}`)
        }

        this.projects = await response.json()
      } catch (error) {
        this.error = error instanceof Error ? error.message : 'Unknown error'
      } finally {
        this.loading = false
      }
    },
    async fetchJobs() {
      this.loading = true
      this.error = ''

      try {
        const response = await fetch(apiUrl('/api/jobs'))

        if (!response.ok) {
          throw new Error(`Jobs request failed: ${response.status}`)
        }

        this.jobs = await response.json()
      } catch (error) {
        this.error = error instanceof Error ? error.message : 'Unknown error'
      } finally {
        this.loading = false
      }
    },
    async fetchProjectJobs(projectId: number | string) {
      this.loading = true
      this.error = ''

      try {
        const response = await fetch(apiUrl(`/api/projects/${projectId}/jobs`))

        if (!response.ok) {
          throw new Error(`Project jobs request failed: ${response.status}`)
        }

        this.jobs = await response.json()
      } catch (error) {
        this.error = error instanceof Error ? error.message : 'Unknown error'
        this.jobs = []
      } finally {
        this.loading = false
      }
    },
    async deleteProject(projectId: number) {
      this.error = ''

      try {
        const response = await fetch(apiUrl(`/api/projects/${projectId}`), {
          method: 'DELETE',
        })

        if (!response.ok) {
          throw new Error(`Delete project failed: ${response.status}`)
        }

        return true
      } catch (error) {
        this.error = error instanceof Error ? error.message : 'Unknown error'
        return false
      }
    },
    async deleteJob(jobId: number) {
      this.error = ''

      try {
        const response = await fetch(apiUrl(`/api/jobs/${jobId}`), {
          method: 'DELETE',
        })

        if (!response.ok) {
          throw new Error(`Delete job failed: ${response.status}`)
        }

        return true
      } catch (error) {
        this.error = error instanceof Error ? error.message : 'Unknown error'
        return false
      }
    },
    async exportJob(job: Pick<JobCard, 'id' | 'name'>, format: JobExportFormat, scope: JobExportScope = 'all') {
      this.exportingJobIds = [...this.exportingJobIds, job.id]
      this.error = ''

      try {
        const config = exportConfigs[format]
        const searchParams = new URLSearchParams({ export_scope: scope })
        const response = await fetch(apiUrl(`/api/jobs/${job.id}/export/${config.endpoint}?${searchParams.toString()}`))

        if (!response.ok) {
          const payload = await response.json().catch(() => null)
          const detail = typeof payload?.detail === 'string' ? payload.detail : `Export failed: ${response.status}`
          throw new Error(detail)
        }

        const blob = await response.blob()
        const url = URL.createObjectURL(blob)
        const link = document.createElement('a')
        link.href = url
        link.download = parseContentDispositionFilename(response.headers.get('Content-Disposition'))
          ?? buildExportFilename(job, format, scope)
        document.body.appendChild(link)
        link.click()
        link.remove()
        URL.revokeObjectURL(url)
        return true
      } catch (error) {
        this.error = error instanceof Error ? error.message : 'Unknown error'
        return false
      } finally {
        this.exportingJobIds = this.exportingJobIds.filter((id) => id !== job.id)
      }
    },
    async exportLabelMe(job: Pick<JobCard, 'id' | 'name'>, scope: JobExportScope = 'all') {
      return this.exportJob(job, 'labelme', scope)
    },
    async importLabels(jobId: number, formData: FormData): Promise<JobImportReport | null> {
      this.error = ''

      try {
        const response = await fetch(apiUrl(`/api/jobs/${jobId}/import-labels`), {
          method: 'POST',
          body: formData,
        })

        if (!response.ok) {
          const payload = await response.json().catch(() => null)
          const detail = typeof payload?.detail === 'string' ? payload.detail : `Import failed: ${response.status}`
          throw new Error(detail)
        }

        return await response.json()
      } catch (error) {
        this.error = error instanceof Error ? error.message : 'Unknown error'
        return null
      }
    },
  },
  getters: {
    thumbnailUrl: () => resolveThumbnailUrl,
    isExporting: (state) => (jobId: number) => state.exportingJobIds.includes(jobId),
  },
})
