import { resolveApiUrl } from './api.ts'
import { parseContentDispositionFilename } from './download.ts'

export type ChecklistMappingProfile = {
  id: number
  name: string
  version: number
  status: string
  key: string
}

export type ChecklistAnnotationSet = {
  annotation_set_id: number
  status: string
  version: number
  protocol_id: number
  protocol_name: string
  segment_count: number
  coverage_percent: number
  error_count: number
  warning_count: number
  updated_at: string
  submitted_at: string | null
  available_mapping_profiles: ChecklistMappingProfile[]
}

export type ChecklistItem = {
  video: {
    id: number
    display_name: string
    status: string
    duration_ms: number | null
    fps: number | null
    frame_count: number
    width: number | null
    height: number | null
    created_at: string
    thumbnail_url: string | null
  }
  trim: {
    origin_type: string
    is_trimmed: boolean
    source_video_id: number | null
    source_video_display_name: string | null
    trim_start_frame: number | null
    trim_end_frame_exclusive: number | null
    trim_start_time_ms: number | null
    trim_end_time_ms: number | null
    kept_frame_count: number | null
    kept_duration_ms: number | null
    derived_video_count: number
    derived_video_ids: number[]
    latest_derived_at: string | null
    derived_videos: Array<{
      video_id: number
      display_name: string
      trim_start_frame: number | null
      trim_end_frame_exclusive: number | null
      created_at: string
    }>
  }
  phase: {
    annotation_set_count: number
    draft_count: number
    submitted_count: number
    latest_annotation_set_id: number | null
    latest_status: string | null
    latest_version: number | null
    latest_protocol_id: number | null
    latest_protocol_name: string | null
    latest_segment_count: number
    latest_coverage_percent: number
    latest_error_count: number
    latest_warning_count: number
    latest_updated_at: string | null
    latest_submitted_at: string | null
    sets: ChecklistAnnotationSet[]
  }
}

export type ChecklistPage = {
  items: ChecklistItem[]
  page: number
  page_size: number
  total: number
  stats: {
    total_videos: number
    trimmed_videos: number
    source_with_derivatives: number
    phase_submitted: number
    phase_not_started: number
  }
}

export type ChecklistDefaultPhaseSelection = {
  video_id: number
  annotation_set_id: number
  status: string
  version: number
  submitted_at: string | null
  protocol_id: number
  protocol_name: string
}

export type PhaseExportSelection = {
  annotationSetId: number
  mappingProfileId: number | null
}

export type VideoExportSelection = {
  includeTrimInfo: boolean
  phaseExports: PhaseExportSelection[]
}

export type BatchExportRequest = {
  items: Array<{
    video_id: number
    include_trim_info: boolean
    phase_exports: Array<{
      annotation_set_id: number
      mapping_profile_id: number | null
    }>
  }>
  include_summary_csv: boolean
  batch_name?: string | null
}

export function emptySelection(): VideoExportSelection {
  return { includeTrimInfo: false, phaseExports: [] }
}

export function cloneSelection(selection: VideoExportSelection | undefined): VideoExportSelection {
  return {
    includeTrimInfo: Boolean(selection?.includeTrimInfo),
    phaseExports: selection?.phaseExports.map((item) => ({ ...item })) ?? [],
  }
}

export function setTrimSelection(
  selections: Map<number, VideoExportSelection>,
  videoId: number,
  includeTrimInfo: boolean,
) {
  const next = cloneSelection(selections.get(videoId))
  next.includeTrimInfo = includeTrimInfo
  writeSelection(selections, videoId, next)
}

export function setPhaseExportSelection(
  selections: Map<number, VideoExportSelection>,
  videoId: number,
  annotationSetId: number,
  mappingProfileId: number | null | undefined,
) {
  const next = cloneSelection(selections.get(videoId))
  next.phaseExports = next.phaseExports.filter((item) => item.annotationSetId !== annotationSetId)
  if (mappingProfileId !== undefined) {
    next.phaseExports.push({ annotationSetId, mappingProfileId })
  }
  writeSelection(selections, videoId, next)
}

export function writeSelection(
  selections: Map<number, VideoExportSelection>,
  videoId: number,
  selection: VideoExportSelection,
) {
  if (!selection.includeTrimInfo && selection.phaseExports.length === 0) {
    selections.delete(videoId)
    return
  }
  selections.set(videoId, selection)
}

export function buildBatchExportPayload(
  selections: Map<number, VideoExportSelection>,
  options: { includeSummaryCsv?: boolean; batchName?: string | null } = {},
): BatchExportRequest {
  return {
    items: Array.from(selections.entries())
      .sort(([left], [right]) => left - right)
      .map(([videoId, selection]) => ({
        video_id: videoId,
        include_trim_info: selection.includeTrimInfo,
        phase_exports: selection.phaseExports
          .slice()
          .sort((left, right) => left.annotationSetId - right.annotationSetId || ((left.mappingProfileId ?? 0) - (right.mappingProfileId ?? 0)))
          .map((item) => ({
            annotation_set_id: item.annotationSetId,
            mapping_profile_id: item.mappingProfileId,
          })),
      })),
    include_summary_csv: options.includeSummaryCsv ?? true,
    batch_name: options.batchName?.trim() || null,
  }
}

export function summarizeSelections(selections: Map<number, VideoExportSelection>) {
  let trimCount = 0
  let phaseCount = 0
  for (const selection of selections.values()) {
    if (selection.includeTrimInfo) {
      trimCount += 1
    }
    phaseCount += selection.phaseExports.length
  }
  return {
    videoCount: selections.size,
    trimCount,
    phaseCount,
    hasSelection: trimCount + phaseCount > 0,
  }
}

export function resolveResearchVideoThumbnailUrl(thumbnailUrl: string | null | undefined, videoId?: number): string {
  if (!thumbnailUrl) {
    return ''
  }
  const resolved = resolveApiUrl(thumbnailUrl)
  if (videoId === undefined) {
    return resolved
  }
  const separator = resolved.includes('?') ? '&' : '?'
  return `${resolved}${separator}v=${videoId}`
}

function submittedSortKey(annotationSet: ChecklistAnnotationSet) {
  return [
    Date.parse(annotationSet.submitted_at ?? '') || Number.NEGATIVE_INFINITY,
    annotationSet.version,
    annotationSet.annotation_set_id,
  ] as const
}

export function latestSubmittedSet(item: ChecklistItem): ChecklistAnnotationSet | null {
  const submitted = item.phase.sets
    .filter((annotationSet) => annotationSet.status === 'submitted')
    .sort((left, right) => {
      const leftKey = submittedSortKey(left)
      const rightKey = submittedSortKey(right)
      return rightKey[0] - leftKey[0] || rightKey[1] - leftKey[1] || rightKey[2] - leftKey[2]
    })
  return submitted[0] ?? null
}

export function selectLatestSubmittedPhaseExports(
  selections: Map<number, VideoExportSelection>,
  items: readonly ChecklistItem[],
) {
  let selected = 0
  let skipped = 0
  for (const item of items) {
    const annotationSet = latestSubmittedSet(item)
    if (!annotationSet) {
      skipped += 1
      continue
    }
    setPhaseExportSelection(selections, item.video.id, annotationSet.annotation_set_id, null)
    selected += 1
  }
  return { selected, skipped }
}

export function applyDefaultPhaseSelections(
  selections: Map<number, VideoExportSelection>,
  defaults: readonly ChecklistDefaultPhaseSelection[],
  manuallyOverriddenVideoIds: ReadonlySet<number> = new Set(),
) {
  let selected = 0
  let skippedByOverride = 0
  for (const defaultSelection of defaults) {
    if (manuallyOverriddenVideoIds.has(defaultSelection.video_id)) {
      skippedByOverride += 1
      continue
    }
    setPhaseExportSelection(selections, defaultSelection.video_id, defaultSelection.annotation_set_id, null)
    selected += 1
  }
  return { selected, skippedByOverride }
}

export function resolveBatchDownloadFilename(contentDisposition: string | null, fallbackFilename: string | null | undefined) {
  return parseContentDispositionFilename(contentDisposition) ?? fallbackFilename ?? 'research-video-export.zip'
}
