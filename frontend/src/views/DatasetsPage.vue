<script setup lang="ts">
import { Plus, Picture, UploadFilled } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { storeToRefs } from 'pinia'
import { computed, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'

import AppSidebar from '../components/AppSidebar.vue'
import {
  JOB_UPLOAD_FILE_LIMIT_MESSAGE,
  MAX_JOB_UPLOAD_FILES,
  useDatasetsStore,
  type JobLabelInput,
} from '../stores/datasets'

const router = useRouter()
const { t } = useI18n()
const datasetsStore = useDatasetsStore()
const { creatingProject, error, lastUpload, loadingProjects, projects, uploading } = storeToRefs(datasetsStore)
const imageInputRef = ref<HTMLInputElement | null>(null)
const folderInputRef = ref<HTMLInputElement | null>(null)
const imageFiles = ref<File[]>([])
const folderFiles = ref<File[]>([])
const showProjectDialog = ref(false)
const newProjectName = ref('')
const form = reactive({
  projectId: null as number | null,
  jobName: '',
})
const labelDraft = reactive<JobLabelInput>({
  name: '',
  shape_type: 'polygon',
  color: '#f97316',
})
const labels = ref<JobLabelInput[]>([])

const allowedImageExtensions = new Set(['.png', '.jpg', '.jpeg', '.bmp', '.tif', '.tiff', '.webp'])
const defaultColors = ['#f97316', '#0ea5e9', '#22c55e', '#a855f7', '#ef4444', '#eab308']

type BrowserFile = File & {
  webkitRelativePath?: string
}

const selectedFiles = computed(() => sortFiles(dedupeFiles([...imageFiles.value, ...folderFiles.value])))
const previewFiles = computed(() => selectedFiles.value.slice(0, 100))
const hiddenFileCount = computed(() => Math.max(0, selectedFiles.value.length - previewFiles.value.length))
const canCreateJob = computed(() =>
  form.projectId !== null &&
  form.jobName.trim().length > 0 &&
  labels.value.length > 0 &&
  selectedFiles.value.length > 0,
)

onMounted(async () => {
  await datasetsStore.fetchProjects()
  form.projectId = projects.value[0]?.id ?? null
})

function onImageFilesSelected(event: Event) {
  const input = event.target as HTMLInputElement
  const nextImageFiles = filterImageFiles(Array.from(input.files ?? []))

  if (!canApplySelectedFiles(nextImageFiles, folderFiles.value)) {
    input.value = ''
    return
  }

  imageFiles.value = nextImageFiles
  input.value = ''
}

function onFolderSelected(event: Event) {
  const input = event.target as HTMLInputElement
  const nextFolderFiles = filterImageFiles(Array.from(input.files ?? []))

  if (!canApplySelectedFiles(imageFiles.value, nextFolderFiles)) {
    input.value = ''
    return
  }

  folderFiles.value = nextFolderFiles
  input.value = ''
}

function filterImageFiles(files: File[]): File[] {
  return files.filter((file) => {
    const name = displayPath(file).toLowerCase()
    const filename = file.name.toLowerCase()

    if (filename === '.ds_store' || filename === 'thumbs.db') {
      return false
    }

    const extensionStart = name.lastIndexOf('.')
    if (extensionStart === -1) {
      return false
    }

    return allowedImageExtensions.has(name.slice(extensionStart))
  })
}

function dedupeFiles(files: File[]): File[] {
  const seen = new Set<string>()
  const deduped: File[] = []

  for (const file of files) {
    const key = `${file.name}-${file.size}-${file.lastModified}`
    if (seen.has(key)) {
      continue
    }

    seen.add(key)
    deduped.push(file)
  }

  return deduped
}

function sortFiles(files: File[]): File[] {
  return [...files].sort((left, right) => naturalCompare(displayPath(left), displayPath(right)))
}

function canApplySelectedFiles(nextImageFiles: File[], nextFolderFiles: File[]): boolean {
  const nextSelectedFiles = dedupeFiles([...nextImageFiles, ...nextFolderFiles])

  if (nextSelectedFiles.length > MAX_JOB_UPLOAD_FILES) {
    ElMessage.error(JOB_UPLOAD_FILE_LIMIT_MESSAGE)
    return false
  }

  return true
}

function displayPath(file: File): string {
  return (file as BrowserFile).webkitRelativePath || file.name
}

function naturalCompare(left: string, right: string): number {
  return left.localeCompare(right, undefined, { numeric: true, sensitivity: 'base' })
}

async function createProject() {
  const name = newProjectName.value.trim()
  if (!name) {
    ElMessage.warning(t('datasets.projectNameRequired'))
    return
  }

  const project = await datasetsStore.createProject(name)
  if (!project) {
    ElMessage.error(t('datasets.createProjectFailed'))
    return
  }

  form.projectId = project.id
  newProjectName.value = ''
  showProjectDialog.value = false
  ElMessage.success(t('datasets.projectCreated'))
}

function addLabel() {
  const name = labelDraft.name.trim()
  if (!name) {
    ElMessage.warning(t('datasets.labelNameRequired'))
    return
  }

  if (labels.value.some((label) => label.name.toLowerCase() === name.toLowerCase())) {
    ElMessage.warning(t('datasets.duplicateLabel', { name }))
    return
  }

  labels.value = [
    ...labels.value,
    {
      name,
      shape_type: labelDraft.shape_type,
      color: labelDraft.color || defaultColors[labels.value.length % defaultColors.length],
    },
  ]
  labelDraft.name = ''
  labelDraft.shape_type = 'polygon'
  labelDraft.color = defaultColors[labels.value.length % defaultColors.length]
}

function deleteLabel(index: number) {
  labels.value = labels.value.filter((_, labelIndex) => labelIndex !== index)
}

async function createJob() {
  if (form.projectId === null) {
    ElMessage.warning(t('datasets.selectProject'))
    return
  }

  if (!form.jobName.trim()) {
    ElMessage.warning(t('datasets.jobNameRequired'))
    return
  }

  if (labels.value.length === 0) {
    ElMessage.warning(t('datasets.atLeastOneLabel'))
    return
  }

  if (selectedFiles.value.length === 0) {
    ElMessage.warning(t('datasets.atLeastOneImage'))
    return
  }
  if (selectedFiles.value.length > MAX_JOB_UPLOAD_FILES) {
    ElMessage.warning(JOB_UPLOAD_FILE_LIMIT_MESSAGE)
    return
  }

  const result = await datasetsStore.createJob({
    projectId: form.projectId,
    jobName: form.jobName.trim(),
    labels: labels.value,
    files: selectedFiles.value,
  })

  if (result) {
    ElMessage.success('Job created successfully')
    void router.push('/jobs')
  }
}
</script>

<template>
  <main class="workspace">
    <AppSidebar :subtitle="t('navigation.datasets')" />

    <section class="content">
      <header class="topbar">
        <div>
          <p class="eyebrow">{{ t('datasets.dataManagement') }}</p>
          <h2>{{ t('navigation.datasets') }}</h2>
        </div>
        <router-link to="/jobs">
          <el-button>{{ t('datasets.viewJobs') }}</el-button>
        </router-link>
      </header>

      <section class="dataset-upload-grid">
        <form class="upload-panel" @submit.prevent="createJob">
          <div class="upload-panel-heading">
            <el-icon><UploadFilled /></el-icon>
            <div>
              <h3>{{ t('datasets.createJob') }}</h3>
              <p>{{ t('datasets.createJobHelp') }}</p>
            </div>
          </div>

          <label class="field-label">
            Project
            <div class="project-picker-row">
              <el-select
                v-model="form.projectId"
                :loading="loadingProjects"
                filterable
                :placeholder="t('datasets.selectProjectPlaceholder')"
              >
                <el-option
                  v-for="project in projects"
                  :key="project.id"
                  :label="project.name"
                  :value="project.id"
                />
              </el-select>
              <el-button type="primary" plain @click="showProjectDialog = true">
                <el-icon><Plus /></el-icon>
                New Project
              </el-button>
            </div>
          </label>

          <label class="field-label">
            Job name
            <el-input v-model="form.jobName" placeholder="case001" required />
          </label>

          <section class="label-builder">
            <p class="panel-label">{{ t('datasets.labels') }}</p>
            <div class="label-builder-row">
              <el-input v-model="labelDraft.name" placeholder="layer_down" @keyup.enter="addLabel" />
              <el-select v-model="labelDraft.shape_type" class="shape-type-select">
                <el-option label="polygon" value="polygon" />
                <el-option label="rectangle" value="rectangle" />
                <el-option label="point" value="point" />
              </el-select>
              <input v-model="labelDraft.color" class="label-color-input" type="color" />
              <el-button type="primary" plain @click="addLabel">{{ t('datasets.add') }}</el-button>
            </div>

            <div class="job-label-list">
              <div v-for="(label, index) in labels" :key="`${label.name}-${index}`" class="job-label-item">
                <span class="label-swatch" :style="{ backgroundColor: label.color }"></span>
                <strong>{{ label.name }}</strong>
                <span>{{ label.shape_type }}</span>
                <small>{{ label.color }}</small>
                <el-button size="small" text type="danger" @click="deleteLabel(index)">{{ t('common.delete') }}</el-button>
              </div>
              <p v-if="labels.length === 0" class="muted-text">{{ t('datasets.addLabelHelp') }}</p>
            </div>
          </section>

          <div class="file-pickers">
            <button class="file-picker-button" type="button" @click="imageInputRef?.click()">
              <el-icon><Picture /></el-icon>
              <span>{{ t('datasets.chooseImages') }}</span>
            </button>
            <div class="file-picker-with-hint">
              <button class="file-picker-button" type="button" @click="folderInputRef?.click()">
                <el-icon><Picture /></el-icon>
                <span>{{ t('datasets.chooseFolder') }}</span>
              </button>
              <p class="folder-picker-hint">
                No need to zip. Select the image folder directly.
              </p>
            </div>
            <input
              ref="imageInputRef"
              accept=".png,.jpg,.jpeg,.bmp,.tif,.tiff,.webp,image/*"
              multiple
              type="file"
              @change="onImageFilesSelected"
            />
            <input
              ref="folderInputRef"
              directory
              multiple
              type="file"
              webkitdirectory
              @change="onFolderSelected"
            />
          </div>

          <p class="upload-selection-count">
            {{ selectedFiles.length ? `${selectedFiles.length} images selected` : 'No images selected' }}
          </p>

          <el-alert v-if="error" :title="error" type="error" show-icon />

          <el-button native-type="submit" type="primary" :loading="uploading" :disabled="!canCreateJob">
            Create Job
          </el-button>
        </form>

        <section class="upload-summary">
          <h3>{{ t('datasets.selectedImages') }}</h3>
          <div v-if="selectedFiles.length" class="selected-file-list">
            <p>{{ selectedFiles.length }} images selected. Showing first {{ previewFiles.length }}.</p>
            <div v-for="file in previewFiles" :key="`${file.name}-${file.size}-${file.lastModified}`" class="selected-file">
              <span>{{ displayPath(file) }}</span>
              <small>{{ Math.round(file.size / 1024) }} KB</small>
            </div>
            <p v-if="hiddenFileCount">... {{ hiddenFileCount }} more images not shown.</p>
          </div>
          <p v-else>{{ t('datasets.noImages') }}</p>

          <div v-if="lastUpload" class="upload-result">
            <strong>{{ t('datasets.lastCreatedJob') }}</strong>
            <span>Project #{{ lastUpload.project_id }}</span>
            <span>Job #{{ lastUpload.id }}</span>
            <span>{{ lastUpload.name }}</span>
          </div>
        </section>
      </section>
    </section>

    <el-dialog v-model="showProjectDialog" :title="t('datasets.createProject')" width="420px">
      <label class="field-label">
        Project name
        <el-input v-model="newProjectName" placeholder="Pig Eye OCT" @keyup.enter="createProject" />
      </label>
      <template #footer>
        <el-button @click="showProjectDialog = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="creatingProject" @click="createProject">{{ t('common.create') }}</el-button>
      </template>
    </el-dialog>
  </main>
</template>
