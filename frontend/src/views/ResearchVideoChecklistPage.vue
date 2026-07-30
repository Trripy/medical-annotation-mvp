<script setup lang="ts">
import { ArrowLeft, Download, RefreshRight, Search } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'

import AppSidebar from '../components/AppSidebar.vue'
import { apiUrl } from '../utils/api'
import { downloadBlobWithFilename } from '../utils/download'
import { formatDateTime, formatDuration as formatDurationValue, type SupportedLocale } from '../utils/locale'
import {
  applyDefaultPhaseSelections,
  buildBatchExportPayload,
  cloneSelection,
  latestSubmittedSet,
  resolveResearchVideoThumbnailUrl,
  resolveBatchDownloadFilename,
  selectLatestSubmittedPhaseExports,
  setPhaseExportSelection,
  setTrimSelection,
  summarizeSelections,
  type BatchExportRequest,
  type ChecklistAnnotationSet,
  type ChecklistDefaultPhaseSelection,
  type ChecklistItem,
  type ChecklistPage,
  type VideoExportSelection,
} from '../utils/researchVideoChecklist'

const router = useRouter()
const { locale, t } = useI18n()

const loading = ref(false)
const error = ref('')
const pageData = ref<ChecklistPage | null>(null)
const searchText = ref('')
const filters = reactive({
  videoStatus: 'all',
  trimStatus: 'all',
  phaseStatus: 'all',
  protocolId: null as number | null,
})
const page = ref(1)
const pageSize = ref(50)
const selectedExports = ref<Map<number, VideoExportSelection>>(new Map())
const autoSelectLatestSubmitted = ref(true)
const manuallyOverriddenPhaseVideos = ref<Set<number>>(new Set())
const autoSelectionMessage = ref('')
const thumbnailErrorIds = ref<Set<number>>(new Set())
const thumbnailRetrySeeds = ref<Map<number, number>>(new Map())
const phaseDialogVisible = ref(false)
const phaseDialogItem = ref<ChecklistItem | null>(null)
const previewDialogVisible = ref(false)
const previewLoading = ref(false)
const exportLoading = ref(false)
const batchName = ref('')
const previewResult = ref<{
  video_count: number
  trim_export_count: number
  phase_export_count: number
  original_phase_export_count: number
  mapped_phase_export_count: number
  archive_entry_count: number
  warnings: string[]
  invalid_items: Array<{ message: string; video_id?: number | null; annotation_set_id?: number | null }>
  suggested_filename: string
} | null>(null)

let searchTimer: number | null = null

onMounted(() => {
  void fetchChecklist({ announceAutoSelect: true })
})

watch(searchText, () => {
  if (searchTimer !== null) {
    window.clearTimeout(searchTimer)
  }
  searchTimer = window.setTimeout(() => {
    page.value = 1
    void fetchChecklist()
  }, 300)
})

watch(filters, () => {
  page.value = 1
  void fetchChecklist()
})

const items = computed(() => pageData.value?.items ?? [])
const stats = computed(() => pageData.value?.stats ?? {
  total_videos: 0,
  trimmed_videos: 0,
  source_with_derivatives: 0,
  phase_submitted: 0,
  phase_not_started: 0,
})
const selectionSummary = computed(() => summarizeSelections(selectedExports.value))
const protocolOptions = computed(() => {
  const options = new Map<number, string>()
  for (const item of items.value) {
    for (const annotationSet of item.phase.sets) {
      options.set(annotationSet.protocol_id, annotationSet.protocol_name)
    }
  }
  return Array.from(options.entries()).map(([id, name]) => ({ id, name }))
})
const exportDisabled = computed(() => !selectionSummary.value.hasSelection || exportLoading.value)

function checklistQueryParams(options: { includePaging: boolean }) {
  const params = new URLSearchParams({
    trim_status: filters.trimStatus,
    phase_status: filters.phaseStatus,
  })
  if (options.includePaging) {
    params.set('page', String(page.value))
    params.set('page_size', String(pageSize.value))
  }
  if (searchText.value.trim()) {
    params.set('search', searchText.value.trim())
  }
  if (filters.videoStatus !== 'all') {
    params.set('video_status', filters.videoStatus)
  }
  if (filters.protocolId !== null) {
    params.set('protocol_id', String(filters.protocolId))
  }
  return params
}

async function fetchChecklist(options: { announceAutoSelect?: boolean } = {}) {
  loading.value = true
  error.value = ''
  try {
    const params = checklistQueryParams({ includePaging: true })
    const response = await fetch(apiUrl(`/api/research/video-operation-checklist?${params.toString()}`), { cache: 'no-store' })
    if (!response.ok) {
      throw new Error(`Checklist request failed: ${response.status}`)
    }
    pageData.value = await response.json()
    pruneInvalidSelections()
    thumbnailErrorIds.value = new Set([...thumbnailErrorIds.value].filter((videoId) => items.value.some((item) => item.video.id === videoId)))
    if (autoSelectLatestSubmitted.value) {
      await applyAutoPhaseSelections(options.announceAutoSelect ?? false)
    }
  } catch (fetchError) {
    error.value = fetchError instanceof Error ? fetchError.message : t('videoChecklist.loadFailed')
  } finally {
    loading.value = false
  }
}

async function fetchDefaultPhaseSelections() {
  const params = checklistQueryParams({ includePaging: false })
  const response = await fetch(apiUrl(`/api/research/video-operation-checklist/default-phase-selections?${params.toString()}`), {
    cache: 'no-store',
  })
  if (!response.ok) {
    throw new Error(`Default phase selection request failed: ${response.status}`)
  }
  return await response.json() as ChecklistDefaultPhaseSelection[]
}

async function applyAutoPhaseSelections(announce: boolean) {
  const defaults = await fetchDefaultPhaseSelections()
  const result = applyDefaultPhaseSelections(selectedExports.value, defaults, manuallyOverriddenPhaseVideos.value)
  selectedExports.value = new Map(selectedExports.value)
  const skipped = Math.max(0, (pageData.value?.total ?? defaults.length) - defaults.length)
  autoSelectionMessage.value = [
    t('videoChecklist.autoSelectedSummary', { count: result.selected }),
    t('videoChecklist.noSubmittedSkipped', { count: skipped }),
  ].join('；')
  if (announce) {
    ElMessage.info(autoSelectionMessage.value)
  }
}

async function restoreAutoSelection() {
  autoSelectLatestSubmitted.value = true
  manuallyOverriddenPhaseVideos.value = new Set()
  await applyAutoPhaseSelections(true)
}

function pruneInvalidSelections() {
  const knownVideoIds = new Set(items.value.map((item) => item.video.id))
  for (const [videoId, selection] of selectedExports.value.entries()) {
    if (!knownVideoIds.has(videoId)) {
      continue
    }
    const item = items.value.find((candidate) => candidate.video.id === videoId)
    if (!item) {
      continue
    }
    const knownSetIds = new Set(item.phase.sets.map((annotationSet) => annotationSet.annotation_set_id))
    selection.phaseExports = selection.phaseExports.filter((phaseExport) => knownSetIds.has(phaseExport.annotationSetId))
    if (!selection.includeTrimInfo && selection.phaseExports.length === 0) {
      selectedExports.value.delete(videoId)
    }
  }
}

function getSelection(videoId: number) {
  return cloneSelection(selectedExports.value.get(videoId))
}

function onTrimChecked(item: ChecklistItem, checked: boolean | string | number) {
  setTrimSelection(selectedExports.value, item.video.id, Boolean(checked))
  selectedExports.value = new Map(selectedExports.value)
}

function phaseSelectionLabel(item: ChecklistItem) {
  const selection = selectedExports.value.get(item.video.id)
  const count = selection?.phaseExports.length ?? 0
  if (isLatestSubmittedOriginalSelected(item)) {
    return t('videoChecklist.latestSubmittedOriginal')
  }
  return count > 0 ? t('videoChecklist.phaseSelectedCount', { count }) : t('videoChecklist.notSelected')
}

function openPhaseDialog(item: ChecklistItem) {
  phaseDialogItem.value = item
  phaseDialogVisible.value = true
}

function selectedMappingValue(annotationSetId: number) {
  const item = phaseDialogItem.value
  if (!item) {
    return '__none__'
  }
  const selection = selectedExports.value.get(item.video.id)
  const phaseExport = selection?.phaseExports.find((candidate) => candidate.annotationSetId === annotationSetId)
  if (!phaseExport) {
    return '__none__'
  }
  return phaseExport.mappingProfileId === null ? '__original__' : String(phaseExport.mappingProfileId)
}

function onPhaseExportChange(annotationSet: ChecklistAnnotationSet, value: string | number) {
  const item = phaseDialogItem.value
  if (!item) {
    return
  }
  manuallyOverriddenPhaseVideos.value = new Set([...manuallyOverriddenPhaseVideos.value, item.video.id])
  if (value === '__none__') {
    setPhaseExportSelection(selectedExports.value, item.video.id, annotationSet.annotation_set_id, undefined)
  } else if (value === '__original__') {
    setPhaseExportSelection(selectedExports.value, item.video.id, annotationSet.annotation_set_id, null)
  } else {
    setPhaseExportSelection(selectedExports.value, item.video.id, annotationSet.annotation_set_id, Number(value))
  }
  selectedExports.value = new Map(selectedExports.value)
}

function selectLatestSubmittedForRow(item: ChecklistItem) {
  const annotationSet = latestSubmittedSet(item)
  if (!annotationSet) {
    ElMessage.warning(t('videoChecklist.noSubmittedSet'))
    return
  }
  manuallyOverriddenPhaseVideos.value = new Set([...manuallyOverriddenPhaseVideos.value, item.video.id])
  setPhaseExportSelection(selectedExports.value, item.video.id, annotationSet.annotation_set_id, null)
  selectedExports.value = new Map(selectedExports.value)
}

function selectFilteredTrim() {
  for (const item of items.value) {
    setTrimSelection(selectedExports.value, item.video.id, true)
  }
  selectedExports.value = new Map(selectedExports.value)
}

function selectFilteredLatestPhase() {
  const result = selectLatestSubmittedPhaseExports(selectedExports.value, items.value)
  selectedExports.value = new Map(selectedExports.value)
  ElMessage.info(t('videoChecklist.selectedLatestSubmittedMessage', result))
}

function selectFilteredBoth() {
  selectFilteredTrim()
  selectFilteredLatestPhase()
}

function clearAllSelections() {
  autoSelectLatestSubmitted.value = false
  selectedExports.value = new Map()
}

function isLatestSubmittedOriginalSelected(item: ChecklistItem) {
  const latest = latestSubmittedSet(item)
  const selection = selectedExports.value.get(item.video.id)
  return Boolean(
    latest
    && selection?.phaseExports.length === 1
    && selection.phaseExports[0].annotationSetId === latest.annotation_set_id
    && selection.phaseExports[0].mappingProfileId === null,
  )
}

function thumbnailSrc(item: ChecklistItem) {
  const base = resolveResearchVideoThumbnailUrl(item.video.thumbnail_url, item.video.id)
  if (!base) {
    return ''
  }
  const retrySeed = thumbnailRetrySeeds.value.get(item.video.id) ?? 0
  if (retrySeed === 0) {
    return base
  }
  const separator = base.includes('?') ? '&' : '?'
  return `${base}${separator}retry=${retrySeed}`
}

function thumbnailFailed(videoId: number) {
  return thumbnailErrorIds.value.has(videoId)
}

function markThumbnailFailed(videoId: number) {
  thumbnailErrorIds.value = new Set([...thumbnailErrorIds.value, videoId])
}

function retryThumbnail(videoId: number) {
  const next = new Map(thumbnailRetrySeeds.value)
  next.set(videoId, (next.get(videoId) ?? 0) + 1)
  thumbnailRetrySeeds.value = next
  thumbnailErrorIds.value = new Set([...thumbnailErrorIds.value].filter((id) => id !== videoId))
}

function buildPayload(): BatchExportRequest {
  return buildBatchExportPayload(selectedExports.value, { batchName: batchName.value, includeSummaryCsv: true })
}

async function previewExport() {
  previewLoading.value = true
  try {
    const response = await fetch(apiUrl('/api/research/video-batch-export/preview'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(buildPayload()),
    })
    const payload = await response.json()
    if (!response.ok) {
      throw new Error(payload?.detail ?? `Preview failed: ${response.status}`)
    }
    previewResult.value = payload
    previewDialogVisible.value = true
  } catch (previewError) {
    ElMessage.error(previewError instanceof Error ? previewError.message : t('videoChecklist.previewFailed'))
  } finally {
    previewLoading.value = false
  }
}

async function exportSelected() {
  exportLoading.value = true
  try {
    const response = await fetch(apiUrl('/api/research/video-batch-export'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(buildPayload()),
    })
    if (!response.ok) {
      const detail = await response.json().catch(() => null)
      throw new Error(detail?.detail ?? `Export failed: ${response.status}`)
    }
    const blob = await response.blob()
    const filename = resolveBatchDownloadFilename(
      response.headers.get('Content-Disposition'),
      previewResult.value?.suggested_filename,
    )
    downloadBlobWithFilename({ blob, filename })
    previewDialogVisible.value = false
    ElMessage.success(t('videoChecklist.exportStarted'))
  } catch (exportError) {
    ElMessage.error(exportError instanceof Error ? exportError.message : t('videoChecklist.exportFailed'))
  } finally {
    exportLoading.value = false
  }
}

function trimStatusText(item: ChecklistItem) {
  if (item.trim.is_trimmed && item.trim.derived_video_count > 0) {
    return t('videoChecklist.trimmedWithDerivatives')
  }
  if (item.trim.is_trimmed) {
    return t('videoChecklist.trimmedResult')
  }
  if (item.trim.derived_video_count > 0) {
    return t('videoChecklist.hasDerivedVideos', { count: item.trim.derived_video_count })
  }
  return item.trim.origin_type === 'server_imported' ? t('videoChecklist.serverImported') : t('videoChecklist.originalVideo')
}

function phaseStatusText(item: ChecklistItem) {
  if (item.phase.annotation_set_count === 0) {
    return t('videoChecklist.notStarted')
  }
  if (item.phase.draft_count > 0 && item.phase.submitted_count > 0) {
    return t('videoChecklist.draftAndSubmitted')
  }
  if (item.phase.submitted_count > 0) {
    return t('videoChecklist.submitted')
  }
  return t('videoChecklist.draft')
}

function formatDuration(durationMs: number | null) {
  return durationMs && durationMs > 0 ? formatDurationValue(durationMs) : t('common.unknown')
}

function formatFrameRange(start: number | null, end: number | null) {
  if (start === null || end === null) {
    return t('common.unknown')
  }
  return `${start + 1}-${end}`
}
</script>

<template>
  <main class="workspace">
    <AppSidebar :subtitle="t('research.subtitle')" />
    <section class="content research-video-checklist-page">
      <header class="topbar">
        <div>
          <p class="eyebrow">{{ t('videoChecklist.entry') }}</p>
          <h2>{{ t('videoChecklist.title') }}</h2>
          <p class="page-subtitle">{{ t('videoChecklist.subtitle') }}</p>
        </div>
        <div class="topbar-actions">
          <el-button @click="router.push('/research/videos')">
            <el-icon><ArrowLeft /></el-icon>
            {{ t('videoChecklist.backToVideos') }}
          </el-button>
          <el-button :loading="loading" @click="fetchChecklist">
            <el-icon><RefreshRight /></el-icon>
            {{ t('common.refresh') }}
          </el-button>
          <el-button type="primary" :disabled="exportDisabled" :loading="previewLoading" @click="previewExport">
            <el-icon><Download /></el-icon>
            {{ t('videoChecklist.exportSelected') }}
          </el-button>
        </div>
      </header>

      <el-alert v-if="error" :title="error" type="error" show-icon>
        <template #default>
          <el-button size="small" @click="fetchChecklist">{{ t('common.refresh') }}</el-button>
        </template>
      </el-alert>

      <section class="checklist-stats">
        <div class="checklist-stat"><span>{{ t('videoChecklist.totalVideos') }}</span><strong>{{ stats.total_videos }}</strong></div>
        <div class="checklist-stat"><span>{{ t('videoChecklist.trimmedVideos') }}</span><strong>{{ stats.trimmed_videos }}</strong></div>
        <div class="checklist-stat"><span>{{ t('videoChecklist.sourceWithDerivatives') }}</span><strong>{{ stats.source_with_derivatives }}</strong></div>
        <div class="checklist-stat"><span>{{ t('videoChecklist.phaseSubmitted') }}</span><strong>{{ stats.phase_submitted }}</strong></div>
        <div class="checklist-stat"><span>{{ t('videoChecklist.phaseNotStarted') }}</span><strong>{{ stats.phase_not_started }}</strong></div>
      </section>

      <section class="checklist-filters">
        <el-input v-model="searchText" :placeholder="t('videoChecklist.search')" clearable>
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
        <el-select v-model="filters.videoStatus" :placeholder="t('common.status')">
          <el-option label="All" value="all" />
          <el-option label="Ready" value="ready" />
          <el-option label="Processing" value="processing" />
          <el-option label="Failed" value="failed" />
        </el-select>
        <el-select v-model="filters.trimStatus" :placeholder="t('videoChecklist.trimStatus')">
          <el-option :label="t('videoChecklist.all')" value="all" />
          <el-option :label="t('videoChecklist.originalVideo')" value="untrimmed" />
          <el-option :label="t('videoChecklist.hasDerivedVideosPlain')" value="has_derivatives" />
          <el-option :label="t('videoChecklist.trimmedResult')" value="trimmed" />
          <el-option :label="t('videoChecklist.trimmedWithDerivatives')" value="trimmed_with_derivatives" />
        </el-select>
        <el-select v-model="filters.phaseStatus" :placeholder="t('videoChecklist.phaseStatus')">
          <el-option :label="t('videoChecklist.all')" value="all" />
          <el-option :label="t('videoChecklist.notStarted')" value="not_started" />
          <el-option :label="t('videoChecklist.draft')" value="draft" />
          <el-option :label="t('videoChecklist.submitted')" value="submitted" />
          <el-option :label="t('videoChecklist.draftAndSubmitted')" value="draft_and_submitted" />
          <el-option :label="t('status.failed')" value="has_errors" />
          <el-option :label="t('videoChecklist.hasWarnings')" value="has_warnings" />
        </el-select>
        <el-select v-model="filters.protocolId" clearable :placeholder="t('videoChecklist.protocol')">
          <el-option v-for="protocol in protocolOptions" :key="protocol.id" :label="protocol.name" :value="protocol.id" />
        </el-select>
      </section>

      <section class="checklist-bulk-actions">
        <el-switch
          v-model="autoSelectLatestSubmitted"
          :active-text="t('videoChecklist.autoSelectLatestSubmitted')"
          @change="(enabled: boolean | string | number) => enabled ? restoreAutoSelection() : undefined"
        />
        <el-button @click="restoreAutoSelection">{{ t('videoChecklist.restoreAutoSelection') }}</el-button>
        <el-button @click="selectFilteredTrim">{{ t('videoChecklist.selectFilteredTrim') }}</el-button>
        <el-button @click="selectFilteredLatestPhase">{{ t('videoChecklist.selectLatestSubmitted') }}</el-button>
        <el-button @click="selectFilteredBoth">{{ t('videoChecklist.selectFilteredBoth') }}</el-button>
        <el-button text type="danger" @click="clearAllSelections">{{ t('videoChecklist.clearAll') }}</el-button>
      </section>

      <el-alert
        v-if="autoSelectionMessage"
        class="checklist-auto-selection-alert"
        :title="autoSelectionMessage"
        type="info"
        show-icon
        :closable="false"
      />

      <el-table v-loading="loading" :data="items" row-key="video.id" class="checklist-table">
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="checklist-expanded">
              <section>
                <h4>{{ t('videoChecklist.trimDetails') }}</h4>
                <p v-if="row.trim.is_trimmed">
                  {{ t('videoChecklist.sourceVideo') }}: {{ row.trim.source_video_display_name || row.trim.source_video_id || t('common.unknown') }}
                  · {{ t('videoChecklist.keepRange') }} {{ formatFrameRange(row.trim.trim_start_frame, row.trim.trim_end_frame_exclusive) }}
                </p>
                <p v-else>{{ t('videoChecklist.notTrimmedDescription') }}</p>
                <ul v-if="row.trim.derived_videos.length">
                  <li v-for="derived in row.trim.derived_videos" :key="derived.video_id">
                    {{ derived.display_name }} · {{ formatFrameRange(derived.trim_start_frame, derived.trim_end_frame_exclusive) }}
                    <el-button text size="small" @click="router.push(`/research/videos/${derived.video_id}/annotate`)">{{ t('common.open') }}</el-button>
                  </li>
                </ul>
              </section>
              <section>
                <h4>{{ t('videoChecklist.annotationSets') }}</h4>
                <el-table :data="row.phase.sets" size="small">
                  <el-table-column prop="annotation_set_id" label="ID" width="80" />
                  <el-table-column :label="t('videoChecklist.phaseStatus')" prop="status" width="110" />
                  <el-table-column :label="t('videoChecklist.protocol')" prop="protocol_name" />
                  <el-table-column :label="t('videoChecklist.coverage')" width="100">
                    <template #default="{ row: annotationSet }">{{ annotationSet.coverage_percent }}%</template>
                  </el-table-column>
                  <el-table-column :label="t('common.open')" width="100">
                    <template #default="{ row: annotationSet }">
                      <el-button text size="small" @click="router.push(`/research/videos/${row.video.id}/phases?set=${annotationSet.annotation_set_id}`)">{{ t('common.open') }}</el-button>
                    </template>
                  </el-table-column>
                </el-table>
              </section>
            </div>
          </template>
        </el-table-column>
        <el-table-column :label="t('videoChecklist.video')" min-width="280" fixed>
          <template #default="{ row }">
            <div class="checklist-video-cell">
              <div class="checklist-thumbnail">
                <img
                  v-if="thumbnailSrc(row) && !thumbnailFailed(row.video.id)"
                  :key="thumbnailSrc(row)"
                  :src="thumbnailSrc(row)"
                  alt=""
                  loading="lazy"
                  @error="markThumbnailFailed(row.video.id)"
                />
                <el-tooltip v-else :content="t('videoChecklist.thumbnailUnavailable')" placement="top">
                  <button type="button" class="checklist-thumbnail-placeholder" @click="retryThumbnail(row.video.id)">
                    {{ t('videoChecklist.retryThumbnail') }}
                  </button>
                </el-tooltip>
              </div>
              <div>
                <strong>{{ row.video.display_name }}</strong>
                <small>ID {{ row.video.id }} · {{ formatDuration(row.video.duration_ms) }} · {{ row.video.frame_count }} {{ t('videoChecklist.frames') }}</small>
                <small>{{ row.video.fps ? `${row.video.fps.toFixed(2)} fps` : t('common.unknown') }} · {{ formatDateTime(row.video.created_at, locale as SupportedLocale) }}</small>
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column :label="t('videoChecklist.trimStatus')" min-width="220">
          <template #default="{ row }">
            <el-tag>{{ trimStatusText(row) }}</el-tag>
            <p v-if="row.trim.is_trimmed" class="checklist-muted">{{ t('videoChecklist.keepRange') }} {{ formatFrameRange(row.trim.trim_start_frame, row.trim.trim_end_frame_exclusive) }}</p>
          </template>
        </el-table-column>
        <el-table-column :label="t('videoChecklist.phaseStatus')" min-width="240">
          <template #default="{ row }">
            <el-tag :type="row.phase.submitted_count > 0 ? 'success' : row.phase.draft_count > 0 ? 'warning' : 'info'">{{ phaseStatusText(row) }}</el-tag>
            <p class="checklist-muted">
              {{ row.phase.latest_protocol_name || t('videoChecklist.noAnnotationSet') }}
              <span v-if="row.phase.latest_annotation_set_id"> · v{{ row.phase.latest_version }} · {{ row.phase.latest_coverage_percent }}%</span>
            </p>
            <p v-if="row.phase.latest_error_count || row.phase.latest_warning_count" class="checklist-muted">
              {{ t('videoChecklist.errors') }} {{ row.phase.latest_error_count }} · {{ t('videoChecklist.warnings') }} {{ row.phase.latest_warning_count }}
            </p>
          </template>
        </el-table-column>
        <el-table-column :label="t('videoChecklist.exportTrimInfo')" width="150" fixed="right">
          <template #default="{ row }">
            <el-checkbox :model-value="getSelection(row.video.id).includeTrimInfo" @change="onTrimChecked(row, $event)" />
          </template>
        </el-table-column>
        <el-table-column :label="t('videoChecklist.exportPhaseLabels')" width="190" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="openPhaseDialog(row)">{{ phaseSelectionLabel(row) }}</el-button>
          </template>
        </el-table-column>
        <el-table-column :label="t('common.actions')" width="210" fixed="right">
          <template #default="{ row }">
            <el-button text size="small" @click="router.push(`/research/videos/${row.video.id}/annotate`)">{{ t('common.open') }}</el-button>
            <el-button text size="small" @click="router.push(`/research/videos/${row.video.id}/phases`)">{{ t('videoChecklist.openPhase') }}</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="checklist-pagination">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="pageSize"
          layout="total, sizes, prev, pager, next"
          :total="pageData?.total ?? 0"
          :page-sizes="[25, 50, 100]"
          @current-change="fetchChecklist"
          @size-change="fetchChecklist"
        />
      </div>

      <div class="checklist-selection-bar">
        <span>
          {{ t('videoChecklist.selectedExports') }}:
          {{ t('videoChecklist.selectedVideos', { count: selectionSummary.videoCount }) }} ·
          {{ t('videoChecklist.selectedTrimCount', { count: selectionSummary.trimCount }) }} ·
          {{ t('videoChecklist.selectedPhaseCount', { count: selectionSummary.phaseCount }) }}
        </span>
        <div>
          <el-button @click="clearAllSelections">{{ t('videoChecklist.clearAll') }}</el-button>
          <el-button type="primary" :disabled="exportDisabled" :loading="previewLoading" @click="previewExport">{{ t('videoChecklist.previewExport') }}</el-button>
        </div>
      </div>

      <el-dialog v-model="phaseDialogVisible" :title="t('videoChecklist.selectPhaseLabels')" width="720px">
        <div v-if="phaseDialogItem" class="phase-export-list">
          <div class="phase-export-dialog-header">
            <strong>{{ phaseDialogItem.video.display_name }}</strong>
            <el-button size="small" @click="selectLatestSubmittedForRow(phaseDialogItem)">{{ t('videoChecklist.selectLatestSubmitted') }}</el-button>
          </div>
          <div v-if="phaseDialogItem.phase.sets.length === 0" class="research-empty-state">{{ t('videoChecklist.noAnnotationSet') }}</div>
          <div v-for="annotationSet in phaseDialogItem.phase.sets" :key="annotationSet.annotation_set_id" class="phase-export-row">
            <div>
              <strong>#{{ annotationSet.annotation_set_id }} · {{ annotationSet.protocol_name }}</strong>
              <small>v{{ annotationSet.version }} · {{ t(`videoChecklist.${annotationSet.status}`) }} · {{ annotationSet.segment_count }} {{ t('videoChecklist.segments') }} · {{ annotationSet.coverage_percent }}%</small>
              <el-alert v-if="annotationSet.status === 'draft'" :title="t('videoChecklist.draftWarning')" type="warning" :closable="false" />
            </div>
            <el-select :model-value="selectedMappingValue(annotationSet.annotation_set_id)" @change="onPhaseExportChange(annotationSet, $event)">
              <el-option :label="t('videoChecklist.notSelected')" value="__none__" />
              <el-option :label="t('videoChecklist.originalLabels')" value="__original__" />
              <el-option
                v-for="profile in annotationSet.available_mapping_profiles"
                :key="profile.id"
                :label="`${profile.name} v${profile.version}`"
                :value="String(profile.id)"
              />
            </el-select>
          </div>
        </div>
      </el-dialog>

      <el-dialog v-model="previewDialogVisible" :title="t('videoChecklist.exportSummary')" width="560px">
        <el-form label-position="top">
          <el-form-item :label="t('videoChecklist.batchName')">
            <el-input v-model="batchName" :placeholder="t('videoChecklist.batchNamePlaceholder')" />
          </el-form-item>
        </el-form>
        <div v-if="previewResult" class="checklist-preview-summary">
          <p>{{ t('videoChecklist.selectedVideos', { count: previewResult.video_count }) }}</p>
          <p>{{ t('videoChecklist.selectedTrimCount', { count: previewResult.trim_export_count }) }}</p>
          <p>{{ t('videoChecklist.selectedPhaseCount', { count: previewResult.phase_export_count }) }}</p>
          <p>{{ t('videoChecklist.originalAndMappedCount', { original: previewResult.original_phase_export_count, mapped: previewResult.mapped_phase_export_count }) }}</p>
          <p>{{ t('videoChecklist.downloadZip') }}: {{ previewResult.suggested_filename }}</p>
          <el-alert v-for="warning in previewResult.warnings" :key="warning" :title="warning" type="warning" show-icon :closable="false" />
          <el-alert v-if="previewResult.invalid_items.length" :title="t('videoChecklist.invalidItems')" type="error" show-icon :closable="false">
            <ul>
              <li v-for="invalid in previewResult.invalid_items" :key="`${invalid.video_id}-${invalid.annotation_set_id}-${invalid.message}`">{{ invalid.message }}</li>
            </ul>
          </el-alert>
        </div>
        <template #footer>
          <el-button @click="previewDialogVisible = false">{{ t('common.cancel') }}</el-button>
          <el-button type="primary" :loading="exportLoading" :disabled="Boolean(previewResult?.invalid_items.length)" @click="exportSelected">{{ t('videoChecklist.exportSelected') }}</el-button>
        </template>
      </el-dialog>
    </section>
  </main>
</template>

<style scoped>
.research-video-checklist-page {
  padding-bottom: 88px;
}

.checklist-stats,
.checklist-filters,
.checklist-bulk-actions {
  display: grid;
  gap: 12px;
  margin-bottom: 14px;
}

.checklist-stats {
  grid-template-columns: repeat(5, minmax(0, 1fr));
}

.checklist-stat {
  border: 1px solid #d8dee8;
  border-radius: 8px;
  padding: 12px;
  background: #fff;
}

.checklist-stat span,
.checklist-muted,
.checklist-video-cell small,
.phase-export-row small {
  display: block;
  color: #667085;
}

.checklist-stat strong {
  display: block;
  margin-top: 4px;
  font-size: 22px;
}

.checklist-filters {
  grid-template-columns: minmax(220px, 1fr) repeat(4, minmax(150px, 220px));
}

.checklist-bulk-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
}

.checklist-auto-selection-alert {
  margin-bottom: 14px;
}

.checklist-video-cell {
  display: flex;
  gap: 10px;
  align-items: center;
}

.checklist-thumbnail {
  width: 72px;
  height: 44px;
  flex: 0 0 auto;
  overflow: hidden;
  border-radius: 6px;
  background: #e5e7eb;
}

.checklist-thumbnail img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.checklist-thumbnail-placeholder {
  width: 100%;
  height: 100%;
  padding: 0 6px;
  border: 0;
  border-radius: 6px;
  background: #e5e7eb;
  color: #475467;
  font-size: 11px;
  cursor: pointer;
  line-height: 1.2;
}

.checklist-expanded {
  display: grid;
  grid-template-columns: 1fr 1.4fr;
  gap: 20px;
  padding: 12px 24px;
}

.checklist-pagination {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}

.checklist-selection-bar {
  position: fixed;
  right: 24px;
  bottom: 18px;
  left: 292px;
  z-index: 10;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 16px;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  background: #fff;
  box-shadow: 0 12px 32px rgba(15, 23, 42, 0.12);
}

.phase-export-list {
  display: grid;
  gap: 12px;
}

.phase-export-dialog-header,
.phase-export-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.phase-export-row {
  padding: 12px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
}

.checklist-preview-summary {
  display: grid;
  gap: 8px;
}

@media (max-width: 980px) {
  .checklist-stats,
  .checklist-filters,
  .checklist-expanded {
    grid-template-columns: 1fr;
  }

  .checklist-selection-bar {
    left: 16px;
    right: 16px;
  }
}
</style>
