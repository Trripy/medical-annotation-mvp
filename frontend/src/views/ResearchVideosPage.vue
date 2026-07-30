<script setup lang="ts">
import { Clock, Delete, Folder, RefreshRight, Tickets, UploadFilled, VideoPlay } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { storeToRefs } from 'pinia'
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'

import AppSidebar from '../components/AppSidebar.vue'
import { apiUrl } from '../utils/api'
import { useResearchVideosStore, type ServerVideoFileEntry, type ServerVideoImportRoot, type ServerVideoBrowseResult, type ServerVideoScanResult } from '../stores/researchVideos'
import { formatDateTime, formatDuration as formatDurationValue, translateStatus, type SupportedLocale } from '../utils/locale'
import {
  buildImportQueue,
  calculateSelectedSize,
  cancelPendingQueueItems,
  clearFilteredVideos,
  getFilteredScannedVideos,
  getSelectionCheckboxState,
  invertFilteredVideos,
  selectAllVideos,
  selectFilteredVideos,
  type ServerImportQueueItem,
  type ServerImportQueueStatus,
  type ServerVideoSelectionFilter,
} from '../utils/researchServerVideoImportUi'

type ServerImportStep = 'browse' | 'selection' | 'importing' | 'completed'
type ImportQueueItem = ServerImportQueueItem<ServerVideoFileEntry>

const router = useRouter()
const { locale, t } = useI18n()
const researchVideosStore = useResearchVideosStore()
const { error, loading, saving, videos } = storeToRefs(researchVideosStore)
const uploadInputRef = ref<HTMLInputElement | null>(null)
const selectedUploadName = ref('')
const importDialogVisible = ref(false)
const importSourceTab = ref<'local' | 'server'>('local')
const serverRoots = ref<ServerVideoImportRoot[]>([])
const serverRootsEnabled = ref(false)
const loadingRoots = ref(false)
const selectedRootId = ref('')
const serverBrowse = ref<ServerVideoBrowseResult | null>(null)
const serverBrowseLoading = ref(false)
const serverSearch = ref('')
const includeSubfolders = ref(false)
const serverScan = ref<ServerVideoScanResult | null>(null)
const serverScanLoading = ref(false)
const serverImportStep = ref<ServerImportStep>('browse')
const scannedVideos = ref<ServerVideoFileEntry[]>([])
const selectedVideoPaths = ref<Set<string>>(new Set())
const selectionSearch = ref('')
const selectionFilter = ref<ServerVideoSelectionFilter>('all')
const importQueue = ref<ImportQueueItem[]>([])
const importingQueue = ref(false)
const stopQueueRequested = ref(false)

onMounted(() => {
  void researchVideosStore.fetchVideos()
})

const videoCards = computed(() => videos.value)
const filteredDirectories = computed(() => {
  const query = serverSearch.value.trim().toLowerCase()
  const directories = serverBrowse.value?.directories ?? []
  return query ? directories.filter((item) => item.name.toLowerCase().includes(query)) : directories
})
const filteredServerVideos = computed(() => {
  const query = serverSearch.value.trim().toLowerCase()
  const serverVideos = serverBrowse.value?.videos ?? []
  return query ? serverVideos.filter((item) => item.name.toLowerCase().includes(query)) : serverVideos
})
const currentServerPath = computed(() => serverBrowse.value?.relative_path || t('researchVideoImport.server.rootPath'))
const serverBreadcrumbs = computed(() => {
  const path = serverBrowse.value?.relative_path ?? ''
  if (!path) {
    return []
  }
  const parts = path.split('/').filter(Boolean)
  return parts.map((name, index) => ({
    name,
    relativePath: parts.slice(0, index + 1).join('/'),
  }))
})
const queueSummary = computed(() => {
  const total = importQueue.value.length
  const imported = importQueue.value.filter((item) => item.status === 'success').length
  const failed = importQueue.value.filter((item) => item.status === 'failed').length
  const skipped = importQueue.value.filter((item) => item.status === 'skipped').length
  const cancelled = importQueue.value.filter((item) => item.status === 'cancelled').length
  const pending = importQueue.value.filter((item) => item.status === 'pending').length
  return { total, imported, failed, skipped, cancelled, pending }
})
const serverImportStepIndex = computed(() => {
  if (serverImportStep.value === 'browse') {
    return 0
  }
  if (serverImportStep.value === 'selection') {
    return 1
  }
  return 2
})
const filteredScannedVideos = computed(() =>
  getFilteredScannedVideos(scannedVideos.value, selectedVideoPaths.value, selectionSearch.value, selectionFilter.value),
)
const selectedVideoCount = computed(() => selectedVideoPaths.value.size)
const selectedVideoSize = computed(() => calculateSelectedSize(scannedVideos.value, selectedVideoPaths.value))
const selectionCheckboxState = computed(() =>
  getSelectionCheckboxState(filteredScannedVideos.value, selectedVideoPaths.value),
)
const currentImportItem = computed(() => importQueue.value.find((item) => item.status === 'importing') ?? null)
const canStartSelectedImport = computed(() => selectedVideoCount.value > 0 && !importingQueue.value)
const scannedPathLabel = computed(() => serverScan.value?.relative_path || t('researchVideoImport.server.rootPath'))

function clearServerScanState() {
  serverScan.value = null
  scannedVideos.value = []
  selectedVideoPaths.value = new Set()
  selectionSearch.value = ''
  selectionFilter.value = 'all'
}

function clearServerQueueState() {
  importQueue.value = []
  importingQueue.value = false
  stopQueueRequested.value = false
}

function formatDuration(durationMs: number | null) {
  return durationMs && durationMs > 0 ? formatDurationValue(durationMs) : t('common.unknown')
}

function openUploadDialog() {
  importDialogVisible.value = true
  importSourceTab.value = 'local'
}

function chooseLocalFile() {
  uploadInputRef.value?.click()
}

async function handleUploadChange(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) {
    return
  }

  const created = await researchVideosStore.uploadVideo(file, selectedUploadName.value || file.name)
  input.value = ''
  selectedUploadName.value = ''

  if (!created) {
    ElMessage.error(researchVideosStore.error || t('research.videoImportFailed'))
    return
  }

  ElMessage.success(t('research.videoImported'))
  await researchVideosStore.fetchVideos()
}

async function onImportTabChange(tabName: string | number) {
  if (tabName === 'server' && serverRoots.value.length === 0 && !loadingRoots.value) {
    await loadServerRoots()
  }
}

async function loadServerRoots() {
  loadingRoots.value = true
  try {
    const payload = await researchVideosStore.fetchServerImportRoots()
    serverRootsEnabled.value = Boolean(payload?.enabled)
    serverRoots.value = payload?.roots ?? []
    selectedRootId.value = serverRoots.value[0]?.id ?? ''
    if (selectedRootId.value) {
      await browseServerDirectory('')
    }
  } finally {
    loadingRoots.value = false
  }
}

async function browseServerDirectory(relativePath: string) {
  if (!selectedRootId.value) {
    return
  }
  serverBrowseLoading.value = true
  clearServerScanState()
  clearServerQueueState()
  serverImportStep.value = 'browse'
  try {
    const payload = await researchVideosStore.browseServerImportDirectory(selectedRootId.value, relativePath)
    if (payload) {
      serverBrowse.value = payload
      serverSearch.value = ''
    } else {
      ElMessage.error(researchVideosStore.error || t('researchVideoImport.server.importFailed'))
    }
  } finally {
    serverBrowseLoading.value = false
  }
}

async function onServerRootChange() {
  serverBrowse.value = null
  serverSearch.value = ''
  clearServerScanState()
  clearServerQueueState()
  serverImportStep.value = 'browse'
  await browseServerDirectory('')
}

async function importSingleServerVideo(video: ServerVideoFileEntry) {
  if (!selectedRootId.value || saving.value) {
    return
  }
  const created = await researchVideosStore.importServerVideo(selectedRootId.value, video.relative_path)
  if (!created) {
    ElMessage.error(researchVideosStore.error || t('researchVideoImport.server.importFailed'))
    return
  }
  ElMessage.success(t('research.videoImported'))
  await researchVideosStore.fetchVideos()
}

async function scanCurrentFolder() {
  if (!selectedRootId.value || !serverBrowse.value) {
    return
  }
  serverScanLoading.value = true
  clearServerQueueState()
  try {
    const payload = await researchVideosStore.scanServerImportFolder(
      selectedRootId.value,
      serverBrowse.value.relative_path,
      includeSubfolders.value,
    )
    if (payload) {
      serverScan.value = payload
      scannedVideos.value = payload.videos
      selectedVideoPaths.value = selectAllVideos(payload.videos)
      selectionSearch.value = ''
      selectionFilter.value = 'all'
      serverImportStep.value = 'selection'
    } else {
      ElMessage.error(researchVideosStore.error || t('researchVideoImport.server.importFailed'))
    }
  } finally {
    serverScanLoading.value = false
  }
}

async function startBatchImport() {
  if (!selectedRootId.value || importingQueue.value) {
    return
  }
  if (selectedVideoCount.value === 0) {
    ElMessage.warning(t('researchVideoImport.selection.emptySelection'))
    return
  }
  try {
    await ElMessageBox.confirm(
      t('researchVideoImport.selection.confirmImport', {
        count: selectedVideoCount.value,
        size: formatBytes(selectedVideoSize.value),
      }),
      t('researchVideoImport.selection.startImport', { count: selectedVideoCount.value }),
      {
        cancelButtonText: t('common.cancel'),
        confirmButtonText: t('researchVideoImport.selection.startImport', { count: selectedVideoCount.value }),
        type: 'warning',
      },
    )
  } catch {
    return
  }
  importQueue.value = buildImportQueue(scannedVideos.value, selectedVideoPaths.value)
  serverImportStep.value = 'importing'
  importingQueue.value = true
  stopQueueRequested.value = false
  for (const item of importQueue.value) {
    if (stopQueueRequested.value) {
      if (item.status === 'pending') {
        item.status = 'cancelled'
      }
      continue
    }
    if (item.status !== 'pending') {
      continue
    }
    item.status = 'importing'
    const created = await researchVideosStore.importServerVideo(selectedRootId.value, item.relative_path)
    if (created) {
      item.status = 'success'
      item.message = created.name
    } else {
      item.status = 'failed'
      item.message = researchVideosStore.error || t('researchVideoImport.server.importFailed')
    }
  }
  importingQueue.value = false
  serverImportStep.value = 'completed'
  await researchVideosStore.fetchVideos()
  ElMessage.success(t('researchVideoImport.server.importCompleted'))
}

function stopRemainingImports() {
  stopQueueRequested.value = true
  importQueue.value = cancelPendingQueueItems(importQueue.value)
  ElMessage.info(t('researchVideoImport.server.importStopped'))
}

function resetImportDialogState() {
  selectedUploadName.value = ''
  serverSearch.value = ''
  clearServerScanState()
  clearServerQueueState()
  serverImportStep.value = 'browse'
}

function formatBytes(bytes: number) {
  if (bytes < 1024) {
    return `${bytes} B`
  }
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`
  }
  if (bytes < 1024 * 1024 * 1024) {
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  }
  return `${(bytes / 1024 / 1024 / 1024).toFixed(1)} GB`
}

function queueStatusLabel(status: ServerImportQueueStatus) {
  return t(`researchVideoImport.server.${status}`)
}

function queueStatusTagType(status: ServerImportQueueStatus) {
  if (status === 'success') {
    return 'success'
  }
  if (status === 'failed') {
    return 'danger'
  }
  if (status === 'cancelled' || status === 'skipped') {
    return 'warning'
  }
  return 'info'
}

function setScannedVideoSelected(video: ServerVideoFileEntry, checked: boolean) {
  const next = new Set(selectedVideoPaths.value)
  if (checked) {
    next.add(video.relative_path)
  } else {
    next.delete(video.relative_path)
  }
  selectedVideoPaths.value = next
}

function toggleScannedVideo(video: ServerVideoFileEntry) {
  setScannedVideoSelected(video, !selectedVideoPaths.value.has(video.relative_path))
}

function onScannedVideoCheckboxChange(video: ServerVideoFileEntry, checked: string | number | boolean) {
  setScannedVideoSelected(video, Boolean(checked))
}

function selectAllScannedVideos() {
  selectedVideoPaths.value = selectAllVideos(scannedVideos.value)
}

function selectFilteredScannedVideos() {
  selectedVideoPaths.value = selectFilteredVideos(selectedVideoPaths.value, filteredScannedVideos.value)
}

function clearFilteredScannedVideos() {
  selectedVideoPaths.value = clearFilteredVideos(selectedVideoPaths.value, filteredScannedVideos.value)
}

function clearAllScannedSelections() {
  selectedVideoPaths.value = new Set()
}

function invertFilteredScannedVideos() {
  selectedVideoPaths.value = invertFilteredVideos(selectedVideoPaths.value, filteredScannedVideos.value)
}

function toggleFilteredSelectionHeader() {
  if (selectionCheckboxState.value.checked) {
    clearFilteredScannedVideos()
    return
  }
  selectFilteredScannedVideos()
}

function returnToServerBrowse() {
  clearServerScanState()
  clearServerQueueState()
  serverImportStep.value = 'browse'
}

function continueServerImport() {
  clearServerScanState()
  clearServerQueueState()
  serverImportStep.value = 'browse'
}

function openVideo(videoId: number) {
  void router.push(`/research/videos/${videoId}/annotate`)
}

function openTrimVideo(videoId: number) {
  void router.push(`/research/videos/${videoId}/trim`)
}

function openVideoChecklist() {
  void router.push('/research/videos/checklist')
}

async function deleteVideo(videoId: number, name: string) {
  try {
    await ElMessageBox.confirm(
      t('research.deleteResearchVideoConfirm', { name }),
      t('research.deleteResearchVideo'),
      {
        cancelButtonText: t('common.cancel'),
        confirmButtonText: t('common.delete'),
        type: 'warning',
      },
    )
  } catch {
    return
  }

  try {
    const response = await fetch(apiUrl(`/api/research/videos/${videoId}`), { method: 'DELETE' })
    if (!response.ok) {
      throw new Error(`Delete failed: ${response.status}`)
    }
    await researchVideosStore.fetchVideos()
    ElMessage.success(t('research.researchVideoDeleted'))
  } catch (deleteError) {
    ElMessage.error(deleteError instanceof Error ? deleteError.message : t('common.delete'))
  }
}
</script>

<template>
  <main class="workspace">
    <AppSidebar :subtitle="t('research.subtitle')" />

    <section class="content">
      <header class="topbar">
        <div>
          <p class="eyebrow">{{ t('research.experimentalWorkspace') }}</p>
          <h2>{{ t('research.videosTitle') }}</h2>
          <p class="page-subtitle">{{ t('research.videosDescription') }}</p>
        </div>
        <div class="topbar-actions">
          <el-button :loading="loading" @click="researchVideosStore.fetchVideos">
            <el-icon><RefreshRight /></el-icon>
            {{ t('common.refresh') }}
          </el-button>
          <el-button @click="openVideoChecklist">
            <el-icon><Tickets /></el-icon>
            {{ t('videoChecklist.entry') }}
          </el-button>
          <el-button type="primary" :loading="saving" @click="openUploadDialog">
            <el-icon><UploadFilled /></el-icon>
            {{ t('research.importVideo') }}
          </el-button>
        </div>
      </header>

      <el-alert v-if="error" :title="error" type="error" show-icon />

      <section class="research-video-grid">
        <article v-for="video in videoCards" :key="video.id" class="research-video-card">
          <div class="research-video-thumb">
            <img v-if="video.thumbnail_url" :src="video.thumbnail_url" :alt="video.name" />
            <div v-else class="research-video-thumb-empty">
              <el-icon><VideoPlay /></el-icon>
            </div>
          </div>

          <div class="research-video-meta">
            <div class="research-video-title-row">
              <h3>{{ video.name }}</h3>
              <span class="research-video-status" :class="video.status">{{ translateStatus(video.status, t) }}</span>
            </div>
            <p class="research-video-filename">{{ video.original_filename }}</p>
            <div class="research-video-stats">
              <span>{{ formatDuration(video.duration_ms) }}</span>
              <span>{{ video.fps ? `${video.fps.toFixed(2)} fps` : t('research.unknownFps') }}</span>
              <span>{{ t('research.frameCount', { count: video.frame_count }) }}</span>
              <span>{{ video.width && video.height ? `${video.width} x ${video.height}` : t('research.unknownResolution') }}</span>
            </div>
            <div class="research-video-created">
              <el-icon><Clock /></el-icon>
              <span>{{ formatDateTime(video.created_at, locale as SupportedLocale) }}</span>
            </div>
          </div>

          <div class="research-video-actions">
            <el-button type="primary" @click="openVideo(video.id)">
              <el-icon><VideoPlay /></el-icon>
              {{ t('common.open') }}
            </el-button>
            <el-tooltip
              :content="video.status === 'ready' ? t('videoTrim.action') : t('videoTrim.onlyReady')"
              placement="top"
            >
              <span>
                <el-button :disabled="video.status !== 'ready'" @click="openTrimVideo(video.id)">
                  {{ t('videoTrim.action') }}
                </el-button>
              </span>
            </el-tooltip>
            <el-button text type="danger" @click="deleteVideo(video.id, video.name)">
              <el-icon><Delete /></el-icon>
              {{ t('common.delete') }}
            </el-button>
          </div>
        </article>

        <div v-if="!loading && videoCards.length === 0" class="research-empty-state">
          {{ t('research.noVideos') }}
        </div>
      </section>

      <el-dialog
        v-model="importDialogVisible"
        :title="t('research.importDialogTitle')"
        class="research-import-dialog"
        width="min(1120px, 94vw)"
        @closed="resetImportDialogState"
      >
        <el-tabs v-model="importSourceTab" @tab-change="onImportTabChange">
          <el-tab-pane :label="t('researchVideoImport.source.local')" name="local">
            <section class="research-upload-inline research-import-local">
              <el-input v-model="selectedUploadName" :placeholder="t('research.optionalDisplayName')" />
              <el-button type="primary" :loading="saving" @click="chooseLocalFile">
                <el-icon><UploadFilled /></el-icon>
                {{ t('researchVideoImport.source.local') }}
              </el-button>
              <input
                ref="uploadInputRef"
                accept="video/mp4,video/quicktime,video/x-msvideo,video/x-matroska,video/webm"
                class="hidden-file-input"
                type="file"
                @change="handleUploadChange"
              />
              <span class="research-upload-help">{{ t('research.uploadHelp') }}</span>
            </section>
          </el-tab-pane>

          <el-tab-pane :label="t('researchVideoImport.source.server')" name="server">
            <section class="server-video-import-panel">
              <el-alert
                v-if="!serverRootsEnabled && !loadingRoots"
                :title="t('researchVideoImport.server.notConfigured')"
                type="info"
                show-icon
              />

              <template v-else>
                <el-steps :active="serverImportStepIndex" simple class="server-video-stepper">
                  <el-step :title="t('researchVideoImport.steps.browse')" />
                  <el-step :title="t('researchVideoImport.steps.select')" />
                  <el-step :title="t('researchVideoImport.steps.import')" />
                </el-steps>

                <section v-if="serverImportStep === 'browse'" class="server-video-step-body">
                  <div class="server-video-import-toolbar">
                    <el-select
                      v-model="selectedRootId"
                      :loading="loadingRoots"
                      :placeholder="t('researchVideoImport.server.root')"
                      class="server-video-root-select"
                      @change="onServerRootChange"
                    >
                      <el-option v-for="root in serverRoots" :key="root.id" :label="root.name" :value="root.id" />
                    </el-select>
                    <el-button
                      :disabled="!serverBrowse || !serverBrowse.relative_path"
                      @click="browseServerDirectory(serverBrowse?.parent_relative_path ?? '')"
                    >
                      {{ t('researchVideoImport.server.parent') }}
                    </el-button>
                    <el-button :loading="serverBrowseLoading" @click="browseServerDirectory(serverBrowse?.relative_path ?? '')">
                      <el-icon><RefreshRight /></el-icon>
                      {{ t('researchVideoImport.server.refresh') }}
                    </el-button>
                    <el-input
                      v-model="serverSearch"
                      clearable
                      :placeholder="t('researchVideoImport.server.search')"
                      class="server-video-search"
                    />
                  </div>

                  <div class="server-video-breadcrumb">
                    <span>{{ t('researchVideoImport.server.currentPath') }}:</span>
                    <button type="button" @click="browseServerDirectory('')">{{ t('researchVideoImport.server.rootPath') }}</button>
                    <template v-for="crumb in serverBreadcrumbs" :key="crumb.relativePath">
                      <span>/</span>
                      <button type="button" @click="browseServerDirectory(crumb.relativePath)">{{ crumb.name }}</button>
                    </template>
                  </div>

                  <div v-loading="serverBrowseLoading" class="server-video-browser">
                    <button
                      v-for="directory in filteredDirectories"
                      :key="`dir-${directory.relative_path}`"
                      class="server-video-browser-row"
                      type="button"
                      @click="browseServerDirectory(directory.relative_path)"
                    >
                      <el-icon><Folder /></el-icon>
                      <span class="server-video-name" :title="directory.name">{{ directory.name }}</span>
                      <span class="server-video-kind">{{ t('researchVideoImport.server.folder') }}</span>
                    </button>

                    <div
                      v-for="video in filteredServerVideos"
                      :key="`video-${video.relative_path}`"
                      class="server-video-browser-row"
                    >
                      <el-icon><VideoPlay /></el-icon>
                      <span class="server-video-name" :title="video.name">{{ video.name }}</span>
                      <span>{{ formatBytes(video.size_bytes) }}</span>
                      <span>{{ formatDateTime(video.modified_at ?? '', locale as SupportedLocale) }}</span>
                      <el-button size="small" :loading="saving" @click="importSingleServerVideo(video)">
                        {{ t('researchVideoImport.server.importFile') }}
                      </el-button>
                    </div>

                    <p
                      v-if="!serverBrowseLoading && serverBrowse && filteredDirectories.length === 0 && filteredServerVideos.length === 0"
                      class="server-video-empty"
                    >
                      {{ serverSearch ? t('researchVideoImport.server.noMatches') : t('researchVideoImport.server.emptyDirectory') }}
                    </p>
                  </div>

                  <div class="server-video-import-actions">
                    <el-checkbox v-model="includeSubfolders">{{ t('researchVideoImport.server.includeSubfolders') }}</el-checkbox>
                    <el-button type="primary" :loading="serverScanLoading" :disabled="!serverBrowse" @click="scanCurrentFolder">
                      {{ t('researchVideoImport.server.scan') }}
                    </el-button>
                  </div>
                </section>

                <section v-else-if="serverImportStep === 'selection' && serverScan" class="server-video-selection-step">
                  <header class="server-video-selection-header">
                    <div>
                      <h3>{{ t('researchVideoImport.selection.title') }}</h3>
                      <p :title="scannedPathLabel">{{ scannedPathLabel }}</p>
                    </div>
                    <div class="server-video-selection-stats">
                      <span>{{ t('researchVideoImport.server.videoCount', { count: serverScan.video_count }) }}</span>
                      <span>{{ t('researchVideoImport.server.totalSize', { size: formatBytes(serverScan.total_size_bytes) }) }}</span>
                      <span>{{ t('researchVideoImport.server.unsupportedCount', { count: serverScan.unsupported_count }) }}</span>
                      <span>{{ t('researchVideoImport.server.unreadableCount', { count: serverScan.unreadable_count }) }}</span>
                      <span>{{ includeSubfolders ? t('researchVideoImport.server.includeSubfolders') : t('researchVideoImport.server.currentFolderOnly') }}</span>
                    </div>
                  </header>
                  <el-alert v-if="serverScan.truncated" :title="t('researchVideoImport.server.truncated')" type="warning" show-icon />

                  <div class="server-video-selection-toolbar">
                    <el-input
                      v-model="selectionSearch"
                      clearable
                      :placeholder="t('researchVideoImport.selection.searchPlaceholder')"
                      class="server-video-selection-search"
                    />
                    <el-select v-model="selectionFilter" class="server-video-selection-filter">
                      <el-option :label="t('researchVideoImport.selection.filterAll')" value="all" />
                      <el-option :label="t('researchVideoImport.selection.filterSelected')" value="selected" />
                      <el-option :label="t('researchVideoImport.selection.filterUnselected')" value="unselected" />
                    </el-select>
                    <el-button @click="selectAllScannedVideos">{{ t('researchVideoImport.selection.selectAll') }}</el-button>
                    <el-button @click="selectFilteredScannedVideos">{{ t('researchVideoImport.selection.selectFiltered') }}</el-button>
                    <el-button @click="clearFilteredScannedVideos">{{ t('researchVideoImport.selection.clearFiltered') }}</el-button>
                    <el-button @click="invertFilteredScannedVideos">{{ t('researchVideoImport.selection.invertFiltered') }}</el-button>
                    <el-button type="danger" text @click="clearAllScannedSelections">
                      {{ t('researchVideoImport.selection.clearAll') }}
                    </el-button>
                  </div>

                  <div class="server-video-selection-list">
                    <div class="server-video-selection-row server-video-selection-row-head">
                      <el-checkbox
                        :model-value="selectionCheckboxState.checked"
                        :indeterminate="selectionCheckboxState.indeterminate"
                        @change="toggleFilteredSelectionHeader"
                      />
                      <span>{{ t('researchVideoImport.server.video') }}</span>
                      <span>{{ t('researchVideoImport.server.size') }}</span>
                      <span>{{ t('researchVideoImport.server.modifiedAt') }}</span>
                      <span>{{ t('researchVideoImport.server.pending') }}</span>
                    </div>

                    <button
                      v-for="video in filteredScannedVideos"
                      :key="video.relative_path"
                      class="server-video-selection-row"
                      :class="{ selected: selectedVideoPaths.has(video.relative_path) }"
                      type="button"
                      @click="toggleScannedVideo(video)"
                      @keydown.enter.prevent="toggleScannedVideo(video)"
                      @keydown.space.prevent="toggleScannedVideo(video)"
                    >
                      <el-checkbox
                        :model-value="selectedVideoPaths.has(video.relative_path)"
                        @click.stop
                        @change="onScannedVideoCheckboxChange(video, $event)"
                      />
                      <span class="server-video-selection-file">
                        <strong :title="video.name">{{ video.name }}</strong>
                        <small :title="video.relative_path">{{ video.relative_path }}</small>
                      </span>
                      <span>{{ formatBytes(video.size_bytes) }}</span>
                      <span>{{ formatDateTime(video.modified_at ?? '', locale as SupportedLocale) }}</span>
                      <el-tag size="small" type="success">{{ t('researchVideoImport.selection.importable') }}</el-tag>
                    </button>

                    <p v-if="filteredScannedVideos.length === 0" class="server-video-empty">
                      {{ t('researchVideoImport.selection.noResults') }}
                    </p>
                  </div>

                  <footer class="server-video-selection-footer">
                    <div>
                      <strong>{{ t('researchVideoImport.selection.selectedCount', { selected: selectedVideoCount, total: scannedVideos.length }) }}</strong>
                      <span>{{ t('researchVideoImport.selection.selectedSize', { size: formatBytes(selectedVideoSize) }) }}</span>
                      <span v-if="selectedVideoCount === 0" class="server-video-selection-warning">
                        {{ t('researchVideoImport.selection.emptySelection') }}
                      </span>
                    </div>
                    <div>
                      <el-button @click="returnToServerBrowse">{{ t('researchVideoImport.selection.backToBrowse') }}</el-button>
                      <el-button type="primary" :disabled="!canStartSelectedImport" @click="startBatchImport">
                        {{ t('researchVideoImport.selection.startImport', { count: selectedVideoCount }) }}
                      </el-button>
                    </div>
                  </footer>
                </section>

                <section v-else class="server-video-import-progress">
                  <header class="server-video-selection-header">
                    <div>
                      <h3>{{ t('researchVideoImport.steps.import') }}</h3>
                      <p v-if="currentImportItem" :title="currentImportItem.relative_path">
                        {{ t('researchVideoImport.server.currentItem', { name: currentImportItem.name }) }}
                      </p>
                    </div>
                    <div class="server-video-selection-stats">
                      <span>{{ t('researchVideoImport.server.batchSummary', queueSummary) }}</span>
                    </div>
                  </header>

                  <div class="server-video-queue">
                    <div
                      v-for="item in importQueue"
                      :key="item.relative_path"
                      class="server-video-queue-row"
                      :class="{ active: item.status === 'importing' }"
                    >
                      <span class="server-video-selection-file">
                        <strong :title="item.name">{{ item.name }}</strong>
                        <small :title="item.relative_path">{{ item.relative_path }}</small>
                      </span>
                      <span>{{ formatBytes(item.size_bytes) }}</span>
                      <el-tag size="small" :type="queueStatusTagType(item.status)">
                        {{ queueStatusLabel(item.status) }}
                      </el-tag>
                      <span class="server-video-message">{{ item.message }}</span>
                    </div>
                  </div>

                  <footer class="server-video-queue-footer">
                    <span>{{ t('researchVideoImport.server.batchSummary', queueSummary) }}</span>
                    <div>
                      <el-button v-if="importingQueue" type="warning" @click="stopRemainingImports">
                        {{ t('researchVideoImport.server.stopRemaining') }}
                      </el-button>
                      <template v-else>
                        <el-button @click="continueServerImport">{{ t('researchVideoImport.server.continueImport') }}</el-button>
                        <el-button type="primary" @click="importDialogVisible = false">
                          {{ t('common.close') }}
                        </el-button>
                      </template>
                    </div>
                  </footer>
                </section>
              </template>
            </section>
          </el-tab-pane>
        </el-tabs>
      </el-dialog>
    </section>
  </main>
</template>
