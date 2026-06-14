import { defineStore } from 'pinia'

import { apiUrl } from '../utils/api'

export type DatasetUploadResult = {
  project_id: number
  id: number
  name: string
  status: string
  images: Array<{
    id: number
    filename: string
    width: number | null
    height: number | null
    frame_index: number | null
    image_url: string
    thumbnail_url: string
  }>
  labels: JobLabelInput[]
}

export type Project = {
  id: number
  name: string
}

export type JobLabelInput = {
  name: string
  shape_type: 'polygon' | 'rectangle' | 'point'
  color: string
}

export const useDatasetsStore = defineStore('datasets', {
  state: () => ({
    projects: [] as Project[],
    loadingProjects: false,
    uploading: false,
    creatingProject: false,
    error: '',
    lastUpload: null as DatasetUploadResult | null,
  }),
  actions: {
    async fetchProjects() {
      this.loadingProjects = true
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
        this.loadingProjects = false
      }
    },
    async createProject(name: string) {
      this.creatingProject = true
      this.error = ''

      try {
        const response = await fetch(apiUrl('/api/projects'), {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ name }),
        })

        if (!response.ok) {
          const body = await response.json().catch(() => null)
          throw new Error(body?.detail ?? `Project creation failed: ${response.status}`)
        }

        const project: Project = await response.json()
        this.projects = [...this.projects.filter((item) => item.id !== project.id), project]
          .sort((left, right) => left.name.localeCompare(right.name, undefined, { sensitivity: 'base' }))
        return project
      } catch (error) {
        this.error = error instanceof Error ? error.message : 'Unknown error'
        return null
      } finally {
        this.creatingProject = false
      }
    },
    async createJob(payload: {
      projectId: number
      jobName: string
      labels: JobLabelInput[]
      files: File[]
    }) {
      this.uploading = true
      this.error = ''

      const formData = new FormData()
      formData.append('project_id', String(payload.projectId))
      formData.append('job_name', payload.jobName)
      formData.append('labels_json', JSON.stringify(payload.labels))
      for (const file of payload.files) {
        formData.append('files', file)
      }

      try {
        const response = await fetch(apiUrl('/api/jobs'), {
          method: 'POST',
          body: formData,
        })

        if (!response.ok) {
          const body = await response.json().catch(() => null)
          throw new Error(body?.detail ?? `Job creation failed: ${response.status}`)
        }

        this.lastUpload = await response.json()
        return this.lastUpload
      } catch (error) {
        this.error = error instanceof Error ? error.message : 'Unknown error'
        return null
      } finally {
        this.uploading = false
      }
    },
  },
})
