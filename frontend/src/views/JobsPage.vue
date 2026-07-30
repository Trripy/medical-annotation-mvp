<script setup lang="ts">
import { ArrowDown, Back, Picture, RefreshRight, Tickets } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { storeToRefs } from 'pinia'
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'

import AppSidebar from '../components/AppSidebar.vue'
import { useAdminStore } from '../stores/admin'
import {
  useJobsStore,
  type JobExportImage,
  type JobCard,
  type JobExportFormat,
  type JobExportRange,
  type JobImportFormat,
  type JobImportMode,
  type JobImportReport,
  type MissingLabelPolicy,
  type ProjectCard,
} from '../stores/jobs'
import { useUsersStore, type UserAccount } from '../stores/users'
import {
  buildJobExportPayload,
  canSubmitJobExport,
  clearFilteredSelection,
  selectFilteredResults,
  toggleImageSelection,
} from '../utils/jobExportUi'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const adminStore = useAdminStore()
const jobsStore = useJobsStore()
const usersStore = useUsersStore()
const { jobs, loading, error, projects } = storeToRefs(jobsStore)
const { isAdmin } = storeToRefs(adminStore)
const { users, loading: usersLoading, error: usersError } = storeToRefs(usersStore)
const newUsername = ref('')
const importFileInput = ref<HTMLInputElement | null>(null)
const importFolderInput = ref<HTMLInputElement | null>(null)
const importModalVisible = ref(false)
const selectedImportJob = ref<JobCard | null>(null)
const importFiles = ref<File[]>([])
const importFormat = ref<JobImportFormat>('auto')
const importMode = ref<JobImportMode>('append')
const missingLabelPolicy = ref<MissingLabelPolicy>('auto_create')
const importingLabels = ref(false)
const importReport = ref<JobImportReport | null>(null)
const exportDialogVisible = ref(false)
const exportTargetJob = ref<JobCard | null>(null)
const exportTargetType = ref<JobExportFormat>('labelme')
const exportRange = ref<JobExportRange>('all')
const includeOriginalImages = ref(false)
const selectedImageIds = ref<Set<number>>(new Set())
const selectorSnapshotImageIds = ref<Set<number>>(new Set())
const imageSelectorVisible = ref(false)
const exportImageItems = ref<JobExportImage[]>([])
const exportImageTotal = ref(0)
const exportImageInitialLoading = ref(false)
const exportImageLoadingMore = ref(false)
const exportImageHasMore = ref(false)
const exportImageGeneration = ref(0)
const exportImageSearch = ref('')
const exportImageStatus = ref<'all' | 'annotated' | 'unannotated'>('all')
const exportImageBatchSize = 72
const imageSelectorGridRef = ref<HTMLElement | null>(null)
const imageSelectorSentinelRef = ref<HTMLElement | null>(null)
const thumbnailErrorIds = ref<Set<number>>(new Set())
let imageSelectorObserver: IntersectionObserver | null = null
let exportImageSearchTimer: ReturnType<typeof setTimeout> | null = null

const exportTypeTitleKeys: Record<JobExportFormat, string> = {
  labelme: 'projects.exportLabelMe',
  overlay: 'projects.exportOverlay',
  'indexed-mask': 'projects.exportIndexedMask',
  'color-mask': 'projects.exportColorMask',
}

const importFormatOptions = computed<Array<{ label: string; value: JobImportFormat }>>(() => [
  { label: t('jobImport.autoDetect'), value: 'auto' },
  { label: 'LabelMe JSON', value: 'labelme' },
  { label: 'COCO JSON', value: 'coco' },
  { label: 'CVAT XML', value: 'cvat' },
  { label: 'YOLO TXT / ZIP', value: 'yolo' },
  { label: 'Mask PNG', value: 'mask' },
  { label: 'Pascal VOC XML', value: 'voc' },
  { label: 'VIA JSON', value: 'via' },
  { label: 'Supervisely JSON', value: 'supervisely' },
])

const importModeOptions = computed<Array<{ label: string; value: JobImportMode; description: string }>>(() => [
  {
    label: t('jobImport.append'),
    value: 'append',
    description: t('jobImport.appendHelp'),
  },
  {
    label: t('jobImport.replaceMatched'),
    value: 'replace_matched_images',
    description: t('jobImport.replaceMatchedHelp'),
  },
  {
    label: t('jobImport.replaceAll'),
    value: 'replace_all_job',
    description: t('jobImport.replaceAllHelp'),
  },
])

const projectId = computed(() => route.params.projectId ? String(route.params.projectId) : '')
const isProjectJobsMode = computed(() => projectId.value.length > 0)
const selectedProject = computed(() =>
  projects.value.find((project) => String(project.id) === projectId.value) ?? null,
)
const projectTitle = computed(() => {
  if (selectedProject.value) {
    return selectedProject.value.name
  }

  if (projectId.value === '0') {
    return t('projects.unassigned')
  }

  return jobs.value[0]?.project_name ?? t('projects.project')
})

watch(
  () => route.params.projectId,
  () => {
    void loadPage()
  },
  { immediate: true },
)

watch(
  isAdmin,
  (enabled) => {
    if (enabled) {
      void usersStore.fetchUsers()
    }
  },
  { immediate: true },
)

async function loadPage() {
  if (isProjectJobsMode.value) {
    await jobsStore.fetchProjects()
    await jobsStore.fetchProjectJobs(projectId.value)
    return
  }

  await jobsStore.fetchProjects()
}

async function addUsername() {
  const added = await usersStore.addUser(newUsername.value)
  if (!added) {
    ElMessage.error(usersStore.error || t('projects.addUserFailed'))
    return
  }

  newUsername.value = ''
  ElMessage.success(t('projects.userAdded'))
}

async function confirmDeleteUser(user: UserAccount) {
  try {
    await ElMessageBox.confirm(
      t('projects.deleteUserConfirm', { username: user.username }),
      t('projects.deleteUser'),
      {
        cancelButtonText: t('common.cancel'),
        confirmButtonText: t('projects.deleteUser'),
        type: 'warning',
      },
    )
  } catch {
    return
  }

  const deleted = await usersStore.deleteUser(user.id)
  if (!deleted) {
    ElMessage.error(usersStore.error || t('projects.deleteUserFailed'))
    return
  }

  ElMessage.success(t('projects.userDeleted'))
}

function refreshPage() {
  void loadPage()
}

function openProject(project: ProjectCard) {
  void router.push(`/jobs/projects/${project.id}`)
}

function backToProjects() {
  void router.push('/jobs')
}

function openJob(job: JobCard) {
  void router.push(`/jobs/${job.id}/annotate`)
}

async function exportJob(job: JobCard, format: JobExportFormat) {
  const payload = buildJobExportPayload(exportRange.value, includeOriginalImages.value, selectedImageIds.value)
  const exported = await jobsStore.exportJob(job, format, {
    exportRange: payload.export_range,
    includeOriginalImages: payload.include_original_images,
    selectedImageIds: payload.selected_image_ids,
  })
  if (exported) {
    closeExportOptions()
    ElMessage.success(t('projects.exportCompleted'))
    return
  }

  ElMessage.error(jobsStore.error || t('projects.exportFailed'))
}

function handleExportCommand(job: JobCard, command: string | number | object) {
  openExportOptions(job, command as JobExportFormat)
}

const exportDialogTitle = computed(() => t(exportTypeTitleKeys[exportTargetType.value]))
const exportAnnotatedImagesCount = computed(() => exportTargetJob.value?.annotated_images_count ?? 0)
const exportEmptyImagesCount = computed(() =>
  Math.max((exportTargetJob.value?.frames ?? 0) - exportAnnotatedImagesCount.value, 0),
)
const selectedExportImageCount = computed(() => selectedImageIds.value.size)
const exportCanSubmit = computed(() => canSubmitJobExport(exportRange.value, selectedExportImageCount.value))
const isExportingTargetJob = computed(() => exportTargetJob.value ? jobsStore.isExporting(exportTargetJob.value.id) : false)

function openExportOptions(job: JobCard, format: JobExportFormat) {
  exportTargetJob.value = job
  exportTargetType.value = format
  exportRange.value = 'all'
  includeOriginalImages.value = false
  selectedImageIds.value = new Set()
  resetImageSelectorState()
  exportDialogVisible.value = true
}

function closeExportOptions() {
  if (exportTargetJob.value && jobsStore.isExporting(exportTargetJob.value.id)) {
    return
  }

  exportDialogVisible.value = false
  exportTargetJob.value = null
  exportTargetType.value = 'labelme'
  exportRange.value = 'all'
  includeOriginalImages.value = false
  selectedImageIds.value = new Set()
  imageSelectorVisible.value = false
  resetImageSelectorState()
}

async function submitExportOptions() {
  if (!exportTargetJob.value) {
    return
  }
  if (!exportCanSubmit.value) {
    ElMessage.warning(t('export.noImagesSelected'))
    return
  }

  await exportJob(exportTargetJob.value, exportTargetType.value)
}

async function openImageSelector() {
  if (!exportTargetJob.value || isExportingTargetJob.value) {
    return
  }

  selectorSnapshotImageIds.value = new Set(selectedImageIds.value)
  imageSelectorVisible.value = true
  resetLoadedExportImages()
  await nextTick()
  setupImageSelectorObserver()
  await loadNextExportImages()
}

function cancelImageSelector() {
  selectedImageIds.value = new Set(selectorSnapshotImageIds.value)
  imageSelectorVisible.value = false
  disconnectImageSelectorObserver()
}

function confirmImageSelector() {
  imageSelectorVisible.value = false
  disconnectImageSelectorObserver()
}

async function loadNextExportImages() {
  if (!exportTargetJob.value || !imageSelectorVisible.value) {
    return
  }
  if (exportImageInitialLoading.value || exportImageLoadingMore.value || !exportImageHasMore.value) {
    return
  }

  const generation = exportImageGeneration.value
  const offset = exportImageItems.value.length
  const isInitialLoad = offset === 0
  exportImageInitialLoading.value = isInitialLoad
  exportImageLoadingMore.value = !isInitialLoad
  const page = await jobsStore.fetchExportImages(exportTargetJob.value.id, {
    search: exportImageSearch.value,
    annotationStatus: exportImageStatus.value,
    limit: exportImageBatchSize,
    offset,
  })
  if (generation !== exportImageGeneration.value) {
    return
  }

  exportImageInitialLoading.value = false
  exportImageLoadingMore.value = false

  if (!page) {
    ElMessage.error(jobsStore.error || t('export.imageListFailed'))
    return
  }

  exportImageItems.value = [...exportImageItems.value, ...page.items]
  exportImageTotal.value = page.total
  exportImageHasMore.value = exportImageItems.value.length < page.total
}

function resetImageSelectorState() {
  disconnectImageSelectorObserver()
  selectorSnapshotImageIds.value = new Set()
  resetLoadedExportImages()
  exportImageSearch.value = ''
  exportImageStatus.value = 'all'
}

function resetLoadedExportImages() {
  exportImageGeneration.value += 1
  exportImageItems.value = []
  exportImageTotal.value = 0
  exportImageInitialLoading.value = false
  exportImageLoadingMore.value = false
  exportImageHasMore.value = true
  thumbnailErrorIds.value = new Set()
}

function isExportImageSelected(imageId: number) {
  return selectedImageIds.value.has(imageId)
}

function setExportImageSelected(imageId: number, selected: boolean) {
  selectedImageIds.value = toggleImageSelection(selectedImageIds.value, imageId, selected)
}

function handleExportImageCheckboxChange(imageId: number, checked: string | number | boolean) {
  setExportImageSelected(imageId, Boolean(checked))
}

function toggleExportImageFromCard(imageId: number) {
  setExportImageSelected(imageId, !isExportImageSelected(imageId))
}

async function selectFilteredExportImages() {
  const matchingIds = await loadFilteredExportImageIds()
  if (!matchingIds) {
    return
  }
  selectedImageIds.value = selectFilteredResults(selectedImageIds.value, matchingIds)
}

async function clearFilteredExportImages() {
  const matchingIds = await loadFilteredExportImageIds()
  if (!matchingIds) {
    return
  }
  selectedImageIds.value = clearFilteredSelection(selectedImageIds.value, matchingIds)
}

function clearAllExportSelections() {
  selectedImageIds.value = new Set()
}

async function loadFilteredExportImageIds() {
  if (!exportTargetJob.value) {
    return null
  }
  const response = await jobsStore.fetchExportImageIds(exportTargetJob.value.id, {
    search: exportImageSearch.value,
    annotationStatus: exportImageStatus.value,
  })
  if (!response) {
    ElMessage.error(jobsStore.error || t('export.imageListFailed'))
    return null
  }
  return response.image_ids
}

function handleThumbnailError(imageId: number) {
  thumbnailErrorIds.value = new Set([...thumbnailErrorIds.value, imageId])
}

function thumbnailFailed(imageId: number) {
  return thumbnailErrorIds.value.has(imageId)
}

function scheduleExportImageReload() {
  if (!imageSelectorVisible.value) {
    return
  }
  if (exportImageSearchTimer) {
    clearTimeout(exportImageSearchTimer)
  }
  exportImageSearchTimer = setTimeout(() => {
    void reloadExportImagesForFilters()
  }, 300)
}

async function reloadExportImagesForFilters() {
  resetLoadedExportImages()
  await nextTick()
  imageSelectorGridRef.value?.scrollTo({ top: 0 })
  setupImageSelectorObserver()
  await loadNextExportImages()
}

function setupImageSelectorObserver() {
  disconnectImageSelectorObserver()
  if (!imageSelectorGridRef.value || !imageSelectorSentinelRef.value) {
    return
  }
  imageSelectorObserver = new IntersectionObserver(
    (entries) => {
      if (entries.some((entry) => entry.isIntersecting)) {
        void loadNextExportImages()
      }
    },
    {
      root: imageSelectorGridRef.value,
      rootMargin: '320px 0px',
      threshold: 0,
    },
  )
  imageSelectorObserver.observe(imageSelectorSentinelRef.value)
}

function disconnectImageSelectorObserver() {
  imageSelectorObserver?.disconnect()
  imageSelectorObserver = null
}

watch([exportImageSearch, exportImageStatus], () => {
  scheduleExportImageReload()
})

onBeforeUnmount(() => {
  disconnectImageSelectorObserver()
  if (exportImageSearchTimer) {
    clearTimeout(exportImageSearchTimer)
  }
})

function openImportModal(job: JobCard) {
  selectedImportJob.value = job
  importModalVisible.value = true
  importFiles.value = []
  importFormat.value = 'auto'
  importMode.value = 'append'
  missingLabelPolicy.value = 'auto_create'
  importReport.value = null
}

function closeImportModal() {
  if (importingLabels.value) {
    return
  }

  importModalVisible.value = false
  selectedImportJob.value = null
  importFiles.value = []
  importReport.value = null
}

function chooseImportFiles() {
  importFileInput.value?.click()
}

function chooseImportFolder() {
  importFolderInput.value?.click()
}

function handleImportFilesChange(event: Event) {
  const input = event.target as HTMLInputElement
  const selectedFiles = Array.from(input.files ?? [])
  if (selectedFiles.length > 0) {
    const existingKeys = new Set(importFiles.value.map(fileKey))
    const nextFiles = selectedFiles.filter((file) => !existingKeys.has(fileKey(file)))
    importFiles.value = [...importFiles.value, ...nextFiles]
    importReport.value = null
  }
  input.value = ''
}

function removeImportFile(index: number) {
  importFiles.value = importFiles.value.filter((_file, fileIndex) => fileIndex !== index)
}

function clearImportFiles() {
  importFiles.value = []
  importReport.value = null
}

function fileKey(file: File) {
  return `${relativeFileName(file)}:${file.size}:${file.lastModified}`
}

function relativeFileName(file: File) {
  return (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name
}

async function submitImportLabels() {
  if (!selectedImportJob.value) {
    return
  }

  if (importFiles.value.length === 0) {
    ElMessage.warning(t('jobImport.noFilesSelected'))
    return
  }

  if (importMode.value !== 'append') {
    const message = importMode.value === 'replace_all_job'
      ? t('jobImport.confirmReplaceAll')
      : t('jobImport.confirmReplaceMatched')
    const confirmButtonText = importMode.value === 'replace_all_job' ? t('jobImport.deleteAndImport') : t('jobImport.continueImport')

    try {
      await ElMessageBox.confirm(message, t('jobImport.confirmStrategyTitle'), {
        cancelButtonText: t('common.cancel'),
        confirmButtonText,
        type: 'warning',
      })
    } catch {
      return
    }
  }

  const formData = new FormData()
  formData.append('format', importFormat.value)
  formData.append('import_mode', importMode.value)
  formData.append('missing_label_policy', missingLabelPolicy.value)
  for (const file of importFiles.value) {
    formData.append('files', file, relativeFileName(file))
  }

  importingLabels.value = true
  importReport.value = null
  const report = await jobsStore.importLabels(selectedImportJob.value.id, formData)
  importingLabels.value = false

  if (!report) {
    ElMessage.error(jobsStore.error || t('jobImport.importFailed'))
    return
  }

  importReport.value = report
  ElMessage.success(t('jobImport.importCompleted'))
  await loadPage()
}

async function confirmDeleteProject(project: ProjectCard) {
  if (!isAdmin.value || project.id === 0) {
    return
  }

  try {
    await ElMessageBox.confirm(
      t('projects.deleteProjectConfirm', { name: project.name }),
      t('projects.deleteProject'),
      {
        cancelButtonText: t('common.cancel'),
        confirmButtonText: t('projects.deleteProject'),
        type: 'warning',
      },
    )
  } catch {
    return
  }

  const deleted = await jobsStore.deleteProject(project.id)
  if (!deleted) {
    ElMessage.error(jobsStore.error || t('projects.deleteProjectFailed'))
    return
  }

  ElMessage.success(t('projects.projectDeleted'))
  await loadPage()
}

async function confirmDeleteJob(job: JobCard) {
  if (!isAdmin.value) {
    return
  }

  try {
    await ElMessageBox.confirm(
      t('projects.deleteJobConfirm', { name: job.name }),
      t('projects.deleteJob'),
      {
        cancelButtonText: t('common.cancel'),
        confirmButtonText: t('projects.deleteJob'),
        type: 'warning',
      },
    )
  } catch {
    return
  }

  const deleted = await jobsStore.deleteJob(job.id)
  if (!deleted) {
    ElMessage.error(jobsStore.error || t('projects.deleteJobFailed'))
    return
  }

  ElMessage.success(t('projects.jobDeleted'))
  await loadPage()
}
</script>

<template>
  <main class="workspace">
    <AppSidebar :subtitle="isProjectJobsMode ? t('projects.projectJobs') : t('navigation.projects')" />

    <section class="content">
      <header class="topbar jobs-topbar">
        <div>
          <p class="eyebrow">{{ isProjectJobsMode ? t('projects.projectJobs') : t('projects.annotationProjects') }}</p>
          <h2>{{ isProjectJobsMode ? `${projectTitle} / ${t('common.job')}` : t('navigation.projects') }}</h2>
        </div>
        <div class="jobs-topbar-actions">
          <el-button v-if="isProjectJobsMode" plain @click="backToProjects">
            <el-icon><Back /></el-icon>
            {{ t('projects.backToProjects') }}
          </el-button>
          <el-button :loading="loading" type="primary" @click="refreshPage">
            <el-icon><RefreshRight /></el-icon>
            {{ t('common.refresh') }}
          </el-button>
        </div>
      </header>

      <el-alert v-if="error" :title="error" type="error" show-icon />
      <el-alert v-if="usersError && isAdmin" :title="usersError" type="error" show-icon />

      <section v-if="isAdmin" class="admin-user-panel">
        <div class="admin-user-panel-header">
          <div>
            <p class="eyebrow">{{ t('navigation.admin') }}</p>
            <h3>{{ t('projects.userManagement') }}</h3>
          </div>
          <form class="admin-user-add" @submit.prevent="addUsername">
            <el-input
              v-model="newUsername"
              clearable
              :placeholder="t('projects.addUsername')"
            />
            <el-button type="primary" :loading="usersLoading" native-type="submit">
              {{ t('common.add') }}
            </el-button>
          </form>
        </div>

        <div v-loading="usersLoading" class="admin-user-list">
          <div v-for="user in users" :key="user.id" class="admin-user-row">
            <span>{{ user.username }}</span>
            <el-button size="small" type="danger" plain @click="confirmDeleteUser(user)">
              {{ t('common.delete') }}
            </el-button>
          </div>
          <p v-if="!usersLoading && users.length === 0" class="admin-user-empty">
            {{ t('projects.noUsers') }}
          </p>
        </div>
      </section>

      <section v-if="!isProjectJobsMode" v-loading="loading" class="jobs-board">
        <article
          v-for="project in projects"
          :key="project.id"
          class="job-card project-card"
          role="button"
          tabindex="0"
          @click="openProject(project)"
          @keydown.enter.prevent="openProject(project)"
        >
          <div class="job-thumb">
            <img
              v-if="jobsStore.thumbnailUrl(project.thumbnail_url)"
              :src="jobsStore.thumbnailUrl(project.thumbnail_url)"
              :alt="`${project.name} thumbnail`"
            />
            <div v-else class="job-thumb-empty">
              <el-icon><Picture /></el-icon>
            </div>
          </div>

          <div class="job-card-body">
            <div class="job-mainline">
              <strong class="job-card-title">{{ project.name }}</strong>
              <el-tag size="small" type="info">
                {{ t('common.project') }}
              </el-tag>
            </div>
            <span v-if="project.id !== 0" class="job-secondary">ID: {{ project.id }}</span>
            <div class="job-meta">
              <span>{{ t('projects.jobsCount', { count: project.job_count }) }}</span>
              <span>{{ t('projects.framesCount', { count: project.frame_count }) }}</span>
            </div>
            <div class="job-card-actions">
              <el-button size="small" type="primary" @click.stop="openProject(project)">
                {{ t('projects.viewJobs') }}
              </el-button>
              <el-button
                v-if="isAdmin && project.id !== 0"
                size="small"
                type="danger"
                plain
                @click.stop="confirmDeleteProject(project)"
              >
                {{ t('projects.deleteProject') }}
              </el-button>
            </div>
          </div>
        </article>

        <div v-if="!loading && projects.length === 0" class="empty-jobs">
          <el-icon><Tickets /></el-icon>
          <p>{{ t('projects.noProjects') }}</p>
        </div>
      </section>

      <section v-else v-loading="loading" class="jobs-board">
        <article
          v-for="job in jobs"
          :key="job.id"
          class="job-card"
          role="button"
          tabindex="0"
          @click="openJob(job)"
          @keydown.enter.prevent="openJob(job)"
        >
          <div class="job-thumb">
            <img
              v-if="jobsStore.thumbnailUrl(job.thumbnail_url)"
              :src="jobsStore.thumbnailUrl(job.thumbnail_url)"
              :alt="`${job.name} thumbnail`"
            />
            <div v-else class="job-thumb-empty">
              <el-icon><Picture /></el-icon>
            </div>
          </div>

          <div class="job-card-body">
            <div class="job-card-header">
              <h3 class="job-card-title" :title="job.name || t('projects.untitledJob')">
                {{ job.name || t('projects.untitledJob') }}
              </h3>
              <el-tag class="job-status-badge" size="small" :type="job.status === 'completed' ? 'success' : 'warning'">
                {{ job.status }}
              </el-tag>
            </div>
            <span class="job-secondary">ID: {{ job.id }}</span>
            <div class="job-meta">
              <span>{{ t('common.project') }}: {{ job.project_name ?? t('projects.noProject') }}</span>
              <span>{{ t('projects.framesCount', { count: job.frames }) }}</span>
            </div>
            <div class="job-card-actions">
              <el-button size="small" type="primary" @click.stop="openJob(job)">
                {{ t('common.open') }}
              </el-button>
              <el-button class="job-import-labels-button" size="small" type="success" plain @click.stop="openImportModal(job)">
                {{ t('jobImport.title') }}
              </el-button>
              <el-dropdown
                trigger="click"
                @click.stop
                @command="handleExportCommand(job, $event)"
              >
                <el-button size="small" plain :loading="jobsStore.isExporting(job.id)" @click.stop>
                  {{ t('common.export') }}
                  <el-icon class="el-icon--right"><ArrowDown /></el-icon>
                </el-button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item command="labelme">
                      LabelMe
                    </el-dropdown-item>
                    <el-dropdown-item command="overlay">
                      {{ t('projects.exportOverlay') }}
                    </el-dropdown-item>
                    <el-dropdown-item command="indexed-mask">
                      {{ t('projects.exportIndexedMask') }}
                    </el-dropdown-item>
                    <el-dropdown-item command="color-mask">
                      {{ t('projects.exportColorMask') }}
                    </el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
              <el-button
                v-if="isAdmin"
                size="small"
                type="danger"
                plain
                @click.stop="confirmDeleteJob(job)"
              >
                {{ t('projects.deleteJob') }}
              </el-button>
            </div>
          </div>
        </article>

        <div v-if="!loading && jobs.length === 0" class="empty-jobs">
          <el-icon><Tickets /></el-icon>
          <p>{{ t('projects.noJobs') }}</p>
        </div>
      </section>
    </section>

    <div v-if="importModalVisible" class="app-modal-backdrop" @click.self="closeImportModal">
      <section class="app-modal import-labels-modal" @click.stop>
        <header class="import-labels-modal-header">
          <div>
            <p class="eyebrow">{{ t('jobImport.title') }}</p>
            <span class="import-current-job-label">{{ t('jobImport.currentJob') }}</span>
            <h2>{{ selectedImportJob?.name || t('common.job') }}</h2>
          </div>
          <el-tag size="small" type="info">{{ t('common.jobWithId', { id: selectedImportJob?.id }) }}</el-tag>
        </header>

        <div class="import-labels-modal-body">
          <section class="import-field">
            <label>{{ t('jobImport.annotationFiles') }}</label>
            <div class="import-file-actions">
              <el-button size="small" @click="chooseImportFiles">{{ t('jobImport.selectFiles') }}</el-button>
              <el-button size="small" @click="chooseImportFolder">{{ t('jobImport.selectFolder') }}</el-button>
              <el-button v-if="importFiles.length" size="small" text @click="clearImportFiles">
                {{ t('common.clear') }}
              </el-button>
            </div>
            <input
              ref="importFileInput"
              class="hidden-file-input"
              type="file"
              multiple
              accept=".json,.xml,.txt,.png,.bmp,.tif,.tiff,.zip"
              @change="handleImportFilesChange"
            />
            <input
              ref="importFolderInput"
              class="hidden-file-input"
              type="file"
              multiple
              webkitdirectory
              @change="handleImportFilesChange"
            />
            <p class="import-help">
              {{ t('jobImport.help') }}
            </p>
            <div v-if="importFiles.length" class="import-file-list">
              <div v-for="(file, index) in importFiles.slice(0, 8)" :key="fileKey(file)" class="import-file-row">
                <span>{{ relativeFileName(file) }}</span>
                <button type="button" :aria-label="t('jobImport.removeFile')" @click="removeImportFile(index)">
                  {{ t('common.remove') }}
                </button>
              </div>
              <p v-if="importFiles.length > 8" class="import-help">
                {{ t('jobImport.moreFilesSelected', { count: importFiles.length - 8 }) }}
              </p>
            </div>
          </section>

          <section class="import-field">
            <label>{{ t('jobImport.format') }}</label>
            <el-select v-model="importFormat" teleported popper-class="settings-select-popper">
              <el-option
                v-for="option in importFormatOptions"
                :key="option.value"
                :label="option.label"
                :value="option.value"
              />
            </el-select>
          </section>

          <section class="import-field">
            <label>{{ t('jobImport.strategy') }}</label>
            <el-radio-group v-model="importMode" class="import-radio-stack">
              <el-radio
                v-for="option in importModeOptions"
                :key="option.value"
                :value="option.value"
              >
                <span class="import-radio-label">{{ option.label }}</span>
                <small>{{ option.description }}</small>
              </el-radio>
            </el-radio-group>
          </section>

          <section class="import-field">
            <label>{{ t('jobImport.missingLabels') }}</label>
            <el-radio-group v-model="missingLabelPolicy" class="import-radio-stack">
              <el-radio value="auto_create">
                <span class="import-radio-label">{{ t('jobImport.autoCreateMissing') }}</span>
                <small>{{ t('jobImport.autoCreateMissingHelp') }}</small>
              </el-radio>
              <el-radio value="skip">
                <span class="import-radio-label">{{ t('jobImport.skipUnknown') }}</span>
                <small>{{ t('jobImport.skipUnknownHelp') }}</small>
              </el-radio>
            </el-radio-group>
          </section>

          <section v-if="importReport" class="import-report">
            <h3>{{ t('jobImport.importCompleted') }}</h3>
            <div class="import-report-grid">
              <span>{{ t('jobImport.formatDetected', { format: importReport.format_detected }) }}</span>
              <span>{{ t('jobImport.matchedImages', { count: importReport.matched_images }) }}</span>
              <span>{{ t('jobImport.createdAnnotations', { count: importReport.created_annotations }) }}</span>
              <span>{{ t('jobImport.createdLabels', { count: importReport.created_labels.length }) }}</span>
              <span>{{ t('jobImport.reassignedColors', { count: importReport.reassigned_conflicting_colors ?? 0 }) }}</span>
              <span>{{ t('jobImport.skipped', { count: importReport.skipped_items.length }) }}</span>
              <span>{{ t('jobImport.errors', { count: importReport.errors.length }) }}</span>
            </div>
            <details
              v-if="
                importReport.skipped_items.length ||
                importReport.errors.length ||
                (importReport.created_label_details?.some((label) => label.color_changed) ?? false)
              "
            >
              <summary>{{ t('common.details') }}</summary>
              <ul>
                <li
                  v-for="label in importReport.created_label_details?.filter((item) => item.color_changed) ?? []"
                  :key="`${label.name}-${label.color}`"
                >
                  {{ t('jobImport.requestedAssignedColor', { name: label.name, requested: label.requested_color ?? t('common.defaultValue'), assigned: label.color }) }}
                </li>
                <li v-for="item in importReport.skipped_items" :key="`${item.source}-${item.reason}`">
                  {{ item.source }}: {{ item.reason }}
                </li>
                <li v-for="errorItem in importReport.errors" :key="errorItem">
                  {{ errorItem }}
                </li>
              </ul>
            </details>
          </section>
        </div>

        <footer class="import-labels-modal-footer">
          <el-button :disabled="importingLabels" @click="closeImportModal">{{ t('common.cancel') }}</el-button>
          <el-button
            type="primary"
            :disabled="importFiles.length === 0"
            :loading="importingLabels"
            @click="submitImportLabels"
          >
            {{ t('jobImport.import') }}
          </el-button>
        </footer>
      </section>
    </div>

    <div v-if="exportDialogVisible" class="app-modal-backdrop" @click.self="closeExportOptions">
      <section class="app-modal export-options-modal" @click.stop>
        <header class="export-options-modal-header">
          <div>
            <p class="eyebrow">{{ t('export.options') }}</p>
            <span class="import-current-job-label">{{ t('export.currentJob') }}</span>
            <h2>{{ exportDialogTitle }}</h2>
          </div>
          <el-tag size="small" type="info">{{ t('common.jobWithId', { id: exportTargetJob?.id }) }}</el-tag>
        </header>

        <div class="export-options-modal-body">
          <section class="export-options-section">
            <h3>{{ t('export.rangeLabel') }}</h3>
            <el-radio-group v-model="exportRange" class="import-radio-stack">
              <el-radio value="all">
                <span class="import-radio-label">{{ t('export.range.all') }}</span>
                <small>{{ t('export.rangeAllHelp') }}</small>
              </el-radio>
              <el-radio value="annotated">
                <span class="import-radio-label">{{ t('export.range.annotated') }}</span>
                <small>{{ t('export.rangeAnnotatedHelp') }}</small>
              </el-radio>
              <el-radio value="selected">
                <span class="import-radio-label">{{ t('export.range.selected') }}</span>
                <small>{{ t('export.rangeSelectedHelp') }}</small>
              </el-radio>
            </el-radio-group>
          </section>

          <section v-if="exportRange === 'selected'" class="export-options-section export-selected-section">
            <div class="export-selected-actions">
              <div>
                <h3>{{ t('export.selectImages') }}</h3>
                <p class="import-help">
                  {{ t('export.selectedImageCount', { count: selectedExportImageCount }) }}
                </p>
              </div>
              <el-button
                size="small"
                :disabled="isExportingTargetJob"
                @click="openImageSelector"
              >
                {{ t('export.selectImagesButton', { count: selectedExportImageCount }) }}
              </el-button>
            </div>
            <p v-if="selectedExportImageCount === 0" class="export-warning-text">
              {{ t('export.noImagesSelected') }}
            </p>
          </section>

          <section class="export-options-section">
            <el-checkbox v-model="includeOriginalImages">
              {{ t('export.includeOriginalImages') }}
            </el-checkbox>
            <p class="import-help">
              {{ t('export.includeOriginalImagesHelp') }}
            </p>
            <p v-if="includeOriginalImages" class="export-warning-text">
              {{ t('export.largeDownloadWarning') }}
            </p>
          </section>

          <section v-if="exportTargetJob" class="export-options-summary">
            <span>{{ t('export.allImagesCount', { count: exportTargetJob.frames }) }}</span>
            <span>{{ t('export.annotatedImagesCount', { count: exportAnnotatedImagesCount }) }}</span>
            <span>{{ t('export.emptyImagesCount', { count: exportEmptyImagesCount }) }}</span>
            <span>{{ t('export.manualSelectedCount', { count: selectedExportImageCount }) }}</span>
          </section>
        </div>

        <footer class="export-options-modal-footer">
          <el-button
            :disabled="isExportingTargetJob"
            @click="closeExportOptions"
          >
            {{ t('common.cancel') }}
          </el-button>
          <el-button
            type="primary"
            :disabled="!exportCanSubmit"
            :loading="isExportingTargetJob"
            @click="submitExportOptions"
          >
            {{ t('common.export') }}
          </el-button>
        </footer>
      </section>
    </div>

    <div v-if="imageSelectorVisible" class="app-modal-backdrop image-selector-backdrop" @click.self="cancelImageSelector">
      <section class="app-modal image-selector-modal" @click.stop>
        <header class="export-options-modal-header">
          <div>
            <p class="eyebrow">{{ t('export.selectImages') }}</p>
            <h2>{{ t('export.selectedImageCount', { count: selectedExportImageCount }) }}</h2>
          </div>
          <el-tag size="small" type="info">{{ t('common.jobWithId', { id: exportTargetJob?.id }) }}</el-tag>
        </header>

        <div class="image-selector-toolbar">
          <el-input
            v-model="exportImageSearch"
            clearable
            :placeholder="t('export.imageSelector.searchPlaceholder')"
          />
          <el-select v-model="exportImageStatus" class="image-selector-status" teleported>
            <el-option :label="t('export.annotationStatusAll')" value="all" />
            <el-option :label="t('export.annotated')" value="annotated" />
            <el-option :label="t('export.unannotated')" value="unannotated" />
          </el-select>
          <el-button size="small" @click="selectFilteredExportImages">
            {{ t('export.imageSelector.selectFilteredResults') }}
          </el-button>
          <el-button size="small" @click="clearFilteredExportImages">
            {{ t('export.imageSelector.clearFilteredSelection') }}
          </el-button>
          <el-button size="small" text @click="clearAllExportSelections">
            {{ t('export.imageSelector.clearAll') }}
          </el-button>
          <span class="image-selector-toolbar-count">
            {{ t('export.imageSelector.selectedCount', { count: selectedExportImageCount }) }}
          </span>
        </div>

        <div ref="imageSelectorGridRef" class="image-selector-grid">
          <p v-if="exportImageInitialLoading" class="image-selector-empty">
            {{ t('export.imageSelector.loading') }}
          </p>
          <article
            v-for="image in exportImageItems"
            :key="image.id"
            class="image-selector-card"
            :class="{ 'is-selected': isExportImageSelected(image.id) }"
            role="button"
            tabindex="0"
            @click="toggleExportImageFromCard(image.id)"
            @keydown.enter.prevent="toggleExportImageFromCard(image.id)"
            @keydown.space.prevent="toggleExportImageFromCard(image.id)"
          >
            <label class="image-selector-check" @click.stop>
              <el-checkbox
                :model-value="isExportImageSelected(image.id)"
                @change="handleExportImageCheckboxChange(image.id, $event)"
              />
            </label>
            <div class="image-selector-thumb">
              <img
                v-if="jobsStore.thumbnailUrl(image.thumbnail_url) && !thumbnailFailed(image.id)"
                :src="jobsStore.thumbnailUrl(image.thumbnail_url)"
                :alt="image.filename"
                loading="lazy"
                @error="handleThumbnailError(image.id)"
              />
              <div v-else class="job-thumb-empty">
                <el-icon><Picture /></el-icon>
              </div>
            </div>
            <div class="image-selector-meta">
              <strong :title="image.filename">{{ image.filename }}</strong>
              <span>ID: {{ image.id }}</span>
              <span>{{ t('export.annotationStatus') }}: {{ image.annotation_count > 0 ? t('export.annotated') : t('export.unannotated') }}</span>
              <span>{{ t('export.annotationCount', { count: image.annotation_count }) }}</span>
            </div>
          </article>
          <p v-if="!exportImageInitialLoading && exportImageItems.length === 0" class="image-selector-empty">
            {{ t('export.imageSelector.noResults') }}
          </p>
          <p v-if="exportImageLoadingMore" class="image-selector-status-row">
            {{ t('export.imageSelector.loadingMore') }}
          </p>
          <p v-if="!exportImageInitialLoading && !exportImageLoadingMore && exportImageItems.length > 0 && !exportImageHasMore" class="image-selector-status-row">
            {{ t('export.imageSelector.allLoaded', { total: exportImageTotal }) }}
          </p>
          <div ref="imageSelectorSentinelRef" class="image-selector-sentinel" aria-hidden="true"></div>
        </div>

        <footer class="image-selector-footer">
          <span>{{ t('export.imageSelector.selectedCount', { count: selectedExportImageCount }) }}</span>
          <div class="image-selector-footer-actions">
            <el-button @click="cancelImageSelector">{{ t('export.imageSelector.cancel') }}</el-button>
            <el-button type="primary" @click="confirmImageSelector">
              {{ t('export.imageSelector.confirm') }}
            </el-button>
          </div>
        </footer>
      </section>
    </div>
  </main>
</template>
