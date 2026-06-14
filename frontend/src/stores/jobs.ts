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

const exportConfigs: Record<JobExportFormat, { endpoint: string; filenameSuffix: string }> = {
  labelme: {
    endpoint: 'labelme',
    filenameSuffix: 'labelme',
  },
  overlay: {
    endpoint: 'overlay',
    filenameSuffix: 'overlay_images',
  },
  'indexed-mask': {
    endpoint: 'indexed-mask',
    filenameSuffix: 'indexed_masks',
  },
  'color-mask': {
    endpoint: 'color-mask',
    filenameSuffix: 'color_masks',
  },
}

function resolveThumbnailUrl(path: string | null): string {
  return resolveApiUrl(path)
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
    async exportJob(jobId: number, format: JobExportFormat) {
      this.exportingJobIds = [...this.exportingJobIds, jobId]
      this.error = ''

      try {
        const config = exportConfigs[format]
        const response = await fetch(apiUrl(`/api/jobs/${jobId}/export/${config.endpoint}`))

        if (!response.ok) {
          throw new Error(`Export failed: ${response.status}`)
        }

        const blob = await response.blob()
        const url = URL.createObjectURL(blob)
        const link = document.createElement('a')
        link.href = url
        link.download = `job_${jobId}_${config.filenameSuffix}.zip`
        document.body.appendChild(link)
        link.click()
        link.remove()
        URL.revokeObjectURL(url)
        return true
      } catch (error) {
        this.error = error instanceof Error ? error.message : 'Unknown error'
        return false
      } finally {
        this.exportingJobIds = this.exportingJobIds.filter((id) => id !== jobId)
      }
    },
    async exportLabelMe(jobId: number) {
      return this.exportJob(jobId, 'labelme')
    },
  },
  getters: {
    thumbnailUrl: () => resolveThumbnailUrl,
    isExporting: (state) => (jobId: number) => state.exportingJobIds.includes(jobId),
  },
})
