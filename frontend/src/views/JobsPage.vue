<script setup lang="ts">
import { ArrowDown, Back, Picture, RefreshRight, Tickets } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { storeToRefs } from 'pinia'
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import AppSidebar from '../components/AppSidebar.vue'
import { useAdminStore } from '../stores/admin'
import {
  useJobsStore,
  type JobCard,
  type JobExportFormat,
  type JobExportScope,
  type JobImportFormat,
  type JobImportMode,
  type JobImportReport,
  type MissingLabelPolicy,
  type ProjectCard,
} from '../stores/jobs'
import { useUsersStore, type UserAccount } from '../stores/users'

const route = useRoute()
const router = useRouter()
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
const exportScope = ref<JobExportScope>('all')

const exportTypeTitles: Record<JobExportFormat, string> = {
  labelme: 'Export LabelMe',
  overlay: 'Export Overlay Images',
  'indexed-mask': 'Export Indexed Masks',
  'color-mask': 'Export Color Masks',
}

const importFormatOptions: Array<{ label: string; value: JobImportFormat }> = [
  { label: 'Auto detect', value: 'auto' },
  { label: 'LabelMe JSON', value: 'labelme' },
  { label: 'COCO JSON', value: 'coco' },
  { label: 'CVAT XML', value: 'cvat' },
  { label: 'YOLO TXT / ZIP', value: 'yolo' },
  { label: 'Mask PNG', value: 'mask' },
  { label: 'Pascal VOC XML', value: 'voc' },
  { label: 'VIA JSON', value: 'via' },
  { label: 'Supervisely JSON', value: 'supervisely' },
]

const importModeOptions: Array<{ label: string; value: JobImportMode; description: string }> = [
  {
    label: 'Append to existing annotations',
    value: 'append',
    description: 'Safe default. Keep all existing annotations and add imported annotations.',
  },
  {
    label: 'Replace annotations of matched images',
    value: 'replace_matched_images',
    description: 'Only delete existing annotations on images matched by imported files. Unmatched images are not affected.',
  },
  {
    label: 'Replace all annotations in this job',
    value: 'replace_all_job',
    description: 'Destructive. Delete all existing annotations in this job before import.',
  },
]

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
    return 'Unassigned Project'
  }

  return jobs.value[0]?.project_name ?? 'Project'
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
    ElMessage.error(usersStore.error || 'Add user failed')
    return
  }

  newUsername.value = ''
  ElMessage.success('User added')
}

async function confirmDeleteUser(user: UserAccount) {
  try {
    await ElMessageBox.confirm(
      `Are you sure you want to delete user "${user.username}"?`,
      'Delete User',
      {
        cancelButtonText: 'Cancel',
        confirmButtonText: 'Delete User',
        type: 'warning',
      },
    )
  } catch {
    return
  }

  const deleted = await usersStore.deleteUser(user.id)
  if (!deleted) {
    ElMessage.error(usersStore.error || 'Delete user failed')
    return
  }

  ElMessage.success('User deleted')
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
  const exported = await jobsStore.exportJob(job, format, exportScope.value)
  if (exported) {
    closeExportOptions()
    ElMessage.success('Export completed')
    return
  }

  ElMessage.error(jobsStore.error || 'Export failed')
}

function handleExportCommand(job: JobCard, command: string | number | object) {
  openExportOptions(job, command as JobExportFormat)
}

const exportDialogTitle = computed(() => exportTypeTitles[exportTargetType.value])
const exportAnnotatedImagesCount = computed(() => exportTargetJob.value?.annotated_images_count ?? 0)
const exportEmptyImagesCount = computed(() =>
  Math.max((exportTargetJob.value?.frames ?? 0) - exportAnnotatedImagesCount.value, 0),
)

function openExportOptions(job: JobCard, format: JobExportFormat) {
  exportTargetJob.value = job
  exportTargetType.value = format
  exportScope.value = 'all'
  exportDialogVisible.value = true
}

function closeExportOptions() {
  if (exportTargetJob.value && jobsStore.isExporting(exportTargetJob.value.id)) {
    return
  }

  exportDialogVisible.value = false
  exportTargetJob.value = null
  exportTargetType.value = 'labelme'
  exportScope.value = 'all'
}

async function submitExportOptions() {
  if (!exportTargetJob.value) {
    return
  }

  await exportJob(exportTargetJob.value, exportTargetType.value)
}

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
    ElMessage.warning('Select at least one annotation file.')
    return
  }

  if (importMode.value !== 'append') {
    const message = importMode.value === 'replace_all_job'
      ? 'This will delete all existing annotations in this job before importing. This action cannot be undone. Continue?'
      : 'This mode may delete existing annotations. Are you sure?'
    const confirmButtonText = importMode.value === 'replace_all_job' ? 'Delete and Import' : 'Continue Import'

    try {
      await ElMessageBox.confirm(message, 'Confirm Import Strategy', {
        cancelButtonText: 'Cancel',
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
    ElMessage.error(jobsStore.error || 'Import failed')
    return
  }

  importReport.value = report
  ElMessage.success('Import completed')
  await loadPage()
}

async function confirmDeleteProject(project: ProjectCard) {
  if (!isAdmin.value || project.id === 0) {
    return
  }

  try {
    await ElMessageBox.confirm(
      `Are you sure you want to delete project "${project.name}"?\nThis will also delete all jobs, images, labels and annotations under this project.`,
      'Delete Project',
      {
        cancelButtonText: 'Cancel',
        confirmButtonText: 'Delete Project',
        type: 'warning',
      },
    )
  } catch {
    return
  }

  const deleted = await jobsStore.deleteProject(project.id)
  if (!deleted) {
    ElMessage.error(jobsStore.error || 'Delete project failed')
    return
  }

  ElMessage.success('Project deleted')
  await loadPage()
}

async function confirmDeleteJob(job: JobCard) {
  if (!isAdmin.value) {
    return
  }

  try {
    await ElMessageBox.confirm(
      `Are you sure you want to delete job "${job.name}"?\nThis will delete all images, labels and annotations under this job.`,
      'Delete Job',
      {
        cancelButtonText: 'Cancel',
        confirmButtonText: 'Delete Job',
        type: 'warning',
      },
    )
  } catch {
    return
  }

  const deleted = await jobsStore.deleteJob(job.id)
  if (!deleted) {
    ElMessage.error(jobsStore.error || 'Delete job failed')
    return
  }

  ElMessage.success('Job deleted')
  await loadPage()
}
</script>

<template>
  <main class="workspace">
    <AppSidebar :subtitle="isProjectJobsMode ? 'Project Jobs' : 'Projects'" />

    <section class="content">
      <header class="topbar jobs-topbar">
        <div>
          <p class="eyebrow">{{ isProjectJobsMode ? 'Project jobs' : 'Annotation projects' }}</p>
          <h2>{{ isProjectJobsMode ? `${projectTitle} / Jobs` : 'Projects' }}</h2>
        </div>
        <div class="jobs-topbar-actions">
          <el-button v-if="isProjectJobsMode" plain @click="backToProjects">
            <el-icon><Back /></el-icon>
            Back to Projects
          </el-button>
          <el-button :loading="loading" type="primary" @click="refreshPage">
            <el-icon><RefreshRight /></el-icon>
            Refresh
          </el-button>
        </div>
      </header>

      <el-alert v-if="error" :title="error" type="error" show-icon />
      <el-alert v-if="usersError && isAdmin" :title="usersError" type="error" show-icon />

      <section v-if="isAdmin" class="admin-user-panel">
        <div class="admin-user-panel-header">
          <div>
            <p class="eyebrow">Admin</p>
            <h3>User Management</h3>
          </div>
          <form class="admin-user-add" @submit.prevent="addUsername">
            <el-input
              v-model="newUsername"
              clearable
              placeholder="Add username"
            />
            <el-button type="primary" :loading="usersLoading" native-type="submit">
              Add
            </el-button>
          </form>
        </div>

        <div v-loading="usersLoading" class="admin-user-list">
          <div v-for="user in users" :key="user.id" class="admin-user-row">
            <span>{{ user.username }}</span>
            <el-button size="small" type="danger" plain @click="confirmDeleteUser(user)">
              Delete
            </el-button>
          </div>
          <p v-if="!usersLoading && users.length === 0" class="admin-user-empty">
            No users yet
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
                Project
              </el-tag>
            </div>
            <span v-if="project.id !== 0" class="job-secondary">ID: {{ project.id }}</span>
            <div class="job-meta">
              <span>Jobs: {{ project.job_count }}</span>
              <span>Frames: {{ project.frame_count }}</span>
            </div>
            <div class="job-card-actions">
              <el-button size="small" type="primary" @click.stop="openProject(project)">
                View Jobs
              </el-button>
              <el-button
                v-if="isAdmin && project.id !== 0"
                size="small"
                type="danger"
                plain
                @click.stop="confirmDeleteProject(project)"
              >
                Delete Project
              </el-button>
            </div>
          </div>
        </article>

        <div v-if="!loading && projects.length === 0" class="empty-jobs">
          <el-icon><Tickets /></el-icon>
          <p>No projects yet</p>
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
              <h3 class="job-card-title" :title="job.name || 'Untitled Job'">
                {{ job.name || 'Untitled Job' }}
              </h3>
              <el-tag class="job-status-badge" size="small" :type="job.status === 'completed' ? 'success' : 'warning'">
                {{ job.status }}
              </el-tag>
            </div>
            <span class="job-secondary">ID: {{ job.id }}</span>
            <div class="job-meta">
              <span>Project: {{ job.project_name ?? 'No project' }}</span>
              <span>Frames: {{ job.frames }}</span>
            </div>
            <div class="job-card-actions">
              <el-button size="small" type="primary" @click.stop="openJob(job)">
                Open
              </el-button>
              <el-button class="job-import-labels-button" size="small" type="success" plain @click.stop="openImportModal(job)">
                Import Labels
              </el-button>
              <el-dropdown
                trigger="click"
                @click.stop
                @command="handleExportCommand(job, $event)"
              >
                <el-button size="small" plain :loading="jobsStore.isExporting(job.id)" @click.stop>
                  Export
                  <el-icon class="el-icon--right"><ArrowDown /></el-icon>
                </el-button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item command="labelme">
                      LabelMe
                    </el-dropdown-item>
                    <el-dropdown-item command="overlay">
                      Overlay Images
                    </el-dropdown-item>
                    <el-dropdown-item command="indexed-mask">
                      Indexed Masks
                    </el-dropdown-item>
                    <el-dropdown-item command="color-mask">
                      Color Masks
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
                Delete Job
              </el-button>
            </div>
          </div>
        </article>

        <div v-if="!loading && jobs.length === 0" class="empty-jobs">
          <el-icon><Tickets /></el-icon>
          <p>No jobs in this project</p>
        </div>
      </section>
    </section>

    <div v-if="importModalVisible" class="app-modal-backdrop" @click.self="closeImportModal">
      <section class="app-modal import-labels-modal" @click.stop>
        <header class="import-labels-modal-header">
          <div>
            <p class="eyebrow">Import labels</p>
            <span class="import-current-job-label">Current Job</span>
            <h2>{{ selectedImportJob?.name || 'Job' }}</h2>
          </div>
          <el-tag size="small" type="info">Job #{{ selectedImportJob?.id }}</el-tag>
        </header>

        <div class="import-labels-modal-body">
          <section class="import-field">
            <label>Annotation files</label>
            <div class="import-file-actions">
              <el-button size="small" @click="chooseImportFiles">Select Files</el-button>
              <el-button size="small" @click="chooseImportFolder">Select Folder</el-button>
              <el-button v-if="importFiles.length" size="small" text @click="clearImportFiles">
                Clear
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
              Supports single files, multiple files, zip archives, and folder upload when supported by the browser.
            </p>
            <div v-if="importFiles.length" class="import-file-list">
              <div v-for="(file, index) in importFiles.slice(0, 8)" :key="fileKey(file)" class="import-file-row">
                <span>{{ relativeFileName(file) }}</span>
                <button type="button" @click="removeImportFile(index)">Remove</button>
              </div>
              <p v-if="importFiles.length > 8" class="import-help">
                +{{ importFiles.length - 8 }} more files selected
              </p>
            </div>
          </section>

          <section class="import-field">
            <label>Import format</label>
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
            <label>Import strategy</label>
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
            <label>Missing labels</label>
            <el-radio-group v-model="missingLabelPolicy" class="import-radio-stack">
              <el-radio value="auto_create">
                <span class="import-radio-label">Auto create missing labels</span>
                <small>New labels are added without deleting existing job labels.</small>
              </el-radio>
              <el-radio value="skip">
                <span class="import-radio-label">Skip unknown labels</span>
                <small>Unknown labels are reported and their annotations are skipped.</small>
              </el-radio>
            </el-radio-group>
          </section>

          <section v-if="importReport" class="import-report">
            <h3>Import completed</h3>
            <div class="import-report-grid">
              <span>Format: {{ importReport.format_detected }}</span>
              <span>Matched images: {{ importReport.matched_images }}</span>
              <span>Created annotations: {{ importReport.created_annotations }}</span>
              <span>Created labels: {{ importReport.created_labels.length }}</span>
              <span>Reassigned conflicting colors: {{ importReport.reassigned_conflicting_colors ?? 0 }}</span>
              <span>Skipped: {{ importReport.skipped_items.length }}</span>
              <span>Errors: {{ importReport.errors.length }}</span>
            </div>
            <details
              v-if="
                importReport.skipped_items.length ||
                importReport.errors.length ||
                (importReport.created_label_details?.some((label) => label.color_changed) ?? false)
              "
            >
              <summary>Details</summary>
              <ul>
                <li
                  v-for="label in importReport.created_label_details?.filter((item) => item.color_changed) ?? []"
                  :key="`${label.name}-${label.color}`"
                >
                  {{ label.name }}: requested {{ label.requested_color ?? 'default' }}, assigned {{ label.color }}
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
          <el-button :disabled="importingLabels" @click="closeImportModal">Cancel</el-button>
          <el-button
            type="primary"
            :disabled="importFiles.length === 0"
            :loading="importingLabels"
            @click="submitImportLabels"
          >
            Import
          </el-button>
        </footer>
      </section>
    </div>

    <div v-if="exportDialogVisible" class="app-modal-backdrop" @click.self="closeExportOptions">
      <section class="app-modal export-options-modal" @click.stop>
        <header class="export-options-modal-header">
          <div>
            <p class="eyebrow">Export options</p>
            <span class="import-current-job-label">Current Job</span>
            <h2>{{ exportDialogTitle }}</h2>
          </div>
          <el-tag size="small" type="info">Job #{{ exportTargetJob?.id }}</el-tag>
        </header>

        <div class="export-options-modal-body">
          <section class="export-options-section">
            <h3>Export range</h3>
            <el-radio-group v-model="exportScope" class="import-radio-stack">
              <el-radio value="all">
                <span class="import-radio-label">All images</span>
                <small>Export labels or masks for all images in this job.</small>
              </el-radio>
              <el-radio value="annotated_only">
                <span class="import-radio-label">Annotated images only</span>
                <small>Export only images that have at least one annotation.</small>
              </el-radio>
            </el-radio-group>
          </section>

          <section v-if="exportTargetJob" class="export-options-summary">
            <span>All images: {{ exportTargetJob.frames }}</span>
            <span>Annotated images: {{ exportAnnotatedImagesCount }}</span>
            <span>Empty images: {{ exportEmptyImagesCount }}</span>
          </section>
        </div>

        <footer class="export-options-modal-footer">
          <el-button
            :disabled="exportTargetJob ? jobsStore.isExporting(exportTargetJob.id) : false"
            @click="closeExportOptions"
          >
            Cancel
          </el-button>
          <el-button
            type="primary"
            :loading="exportTargetJob ? jobsStore.isExporting(exportTargetJob.id) : false"
            @click="submitExportOptions"
          >
            Export
          </el-button>
        </footer>
      </section>
    </div>
  </main>
</template>
