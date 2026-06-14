<script setup lang="ts">
import { Plus, Picture, UploadFilled } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { storeToRefs } from 'pinia'
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'

import AppSidebar from '../components/AppSidebar.vue'
import { useDatasetsStore, type JobLabelInput } from '../stores/datasets'

const router = useRouter()
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
  imageFiles.value = filterImageFiles(Array.from(input.files ?? []))
}

function onFolderSelected(event: Event) {
  const input = event.target as HTMLInputElement
  folderFiles.value = filterImageFiles(Array.from(input.files ?? []))
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

function displayPath(file: File): string {
  return (file as BrowserFile).webkitRelativePath || file.name
}

function naturalCompare(left: string, right: string): number {
  return left.localeCompare(right, undefined, { numeric: true, sensitivity: 'base' })
}

async function createProject() {
  const name = newProjectName.value.trim()
  if (!name) {
    ElMessage.warning('Project name is required')
    return
  }

  const project = await datasetsStore.createProject(name)
  if (!project) {
    ElMessage.error('Failed to create project')
    return
  }

  form.projectId = project.id
  newProjectName.value = ''
  showProjectDialog.value = false
  ElMessage.success('Project created')
}

function addLabel() {
  const name = labelDraft.name.trim()
  if (!name) {
    ElMessage.warning('Label name is required')
    return
  }

  if (labels.value.some((label) => label.name.toLowerCase() === name.toLowerCase())) {
    ElMessage.warning(`Duplicate label: ${name}`)
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
    ElMessage.warning('Please select a project')
    return
  }

  if (!form.jobName.trim()) {
    ElMessage.warning('Job name is required')
    return
  }

  if (labels.value.length === 0) {
    ElMessage.warning('At least one label is required')
    return
  }

  if (selectedFiles.value.length === 0) {
    ElMessage.warning('At least one image is required')
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
    <AppSidebar subtitle="Datasets" />

    <section class="content">
      <header class="topbar">
        <div>
          <p class="eyebrow">Data management</p>
          <h2>Datasets</h2>
        </div>
        <router-link to="/jobs">
          <el-button>View Jobs</el-button>
        </router-link>
      </header>

      <section class="dataset-upload-grid">
        <form class="upload-panel" @submit.prevent="createJob">
          <div class="upload-panel-heading">
            <el-icon><UploadFilled /></el-icon>
            <div>
              <h3>Create Job</h3>
              <p>Select a project, define job labels, and upload images in one step.</p>
            </div>
          </div>

          <label class="field-label">
            Project
            <div class="project-picker-row">
              <el-select
                v-model="form.projectId"
                :loading="loadingProjects"
                filterable
                placeholder="Select project"
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
            <p class="panel-label">Labels</p>
            <div class="label-builder-row">
              <el-input v-model="labelDraft.name" placeholder="layer_down" @keyup.enter="addLabel" />
              <el-select v-model="labelDraft.shape_type" class="shape-type-select">
                <el-option label="polygon" value="polygon" />
                <el-option label="rectangle" value="rectangle" />
                <el-option label="point" value="point" />
              </el-select>
              <input v-model="labelDraft.color" class="label-color-input" type="color" />
              <el-button type="primary" plain @click="addLabel">Add</el-button>
            </div>

            <div class="job-label-list">
              <div v-for="(label, index) in labels" :key="`${label.name}-${index}`" class="job-label-item">
                <span class="label-swatch" :style="{ backgroundColor: label.color }"></span>
                <strong>{{ label.name }}</strong>
                <span>{{ label.shape_type }}</span>
                <small>{{ label.color }}</small>
                <el-button size="small" text type="danger" @click="deleteLabel(index)">Delete</el-button>
              </div>
              <p v-if="labels.length === 0" class="muted-text">Add at least one label before creating a job.</p>
            </div>
          </section>

          <div class="file-pickers">
            <button class="file-picker-button" type="button" @click="imageInputRef?.click()">
              <el-icon><Picture /></el-icon>
              <span>Choose images</span>
            </button>
            <div class="file-picker-with-hint">
              <button class="file-picker-button" type="button" @click="folderInputRef?.click()">
                <el-icon><Picture /></el-icon>
                <span>Choose folder</span>
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
          <h3>Selected Images</h3>
          <div v-if="selectedFiles.length" class="selected-file-list">
            <p>{{ selectedFiles.length }} images selected. Showing first {{ previewFiles.length }}.</p>
            <div v-for="file in previewFiles" :key="`${file.name}-${file.size}-${file.lastModified}`" class="selected-file">
              <span>{{ displayPath(file) }}</span>
              <small>{{ Math.round(file.size / 1024) }} KB</small>
            </div>
            <p v-if="hiddenFileCount">... {{ hiddenFileCount }} more images not shown.</p>
          </div>
          <p v-else>No images selected.</p>

          <div v-if="lastUpload" class="upload-result">
            <strong>Last created job</strong>
            <span>Project #{{ lastUpload.project_id }}</span>
            <span>Job #{{ lastUpload.id }}</span>
            <span>{{ lastUpload.name }}</span>
          </div>
        </section>
      </section>
    </section>

    <el-dialog v-model="showProjectDialog" title="Create Project" width="420px">
      <label class="field-label">
        Project name
        <el-input v-model="newProjectName" placeholder="Pig Eye OCT" @keyup.enter="createProject" />
      </label>
      <template #footer>
        <el-button @click="showProjectDialog = false">Cancel</el-button>
        <el-button type="primary" :loading="creatingProject" @click="createProject">Create</el-button>
      </template>
    </el-dialog>
  </main>
</template>
