import { defineStore } from 'pinia'

import { apiUrl } from '../utils/api.ts'
import { downloadBlobWithFilename, parseContentDispositionFilename } from '../utils/download.ts'
import type {
  CloseActivePhaseSegmentRequest,
  CreateResearchPhaseLabelMappingProfileRequest,
  CreateResearchPhaseAnnotationSetRequest,
  CreateResearchPhaseAnnotationSetResponse,
  CreateResearchPhaseSegmentRequest,
  DuplicateResearchPhaseLabelMappingProfileRequest,
  MergeResearchPhaseMappingClassesRequest,
  MergePhaseSegmentsRequest,
  ReopenPhaseAnnotationSetRequest,
  ResearchPhaseAnnotationSetDetail,
  ResearchPhaseAnnotationSetStatus,
  ResearchPhaseLabelMappingProfileDetail,
  ResearchPhaseLabelMappingProfileSummary,
  ResearchPhaseAnnotationSetSummary,
  ResearchPhaseConflictDetail,
  ResearchPhaseMutationResponse,
  ResearchPhaseProtocolDetail,
  ResearchPhaseProtocolSummary,
  ResearchPhaseStatusMutationResponse,
  ResearchPhaseValidationErrorDetail,
  ResearchPhaseValidationResponse,
  SplitPhaseSegmentRequest,
  SubmitPhaseAnnotationSetRequest,
  TransitionResearchPhaseRequest,
  UnmergeResearchPhaseMappingTargetRequest,
  UpdateResearchPhaseSegmentRequest,
} from '../types/researchPhase.ts'

export type PhaseSaveState = 'idle' | 'saving' | 'saved' | 'error' | 'conflict'
export type PhaseActionErrorKind =
  | 'conflict'
  | 'warning_confirmation'
  | 'validation_error'
  | 'business'
  | 'network'
  | 'readonly'
  | 'missing'
export type PhaseExportKind = 'json' | 'segments' | 'framewise'

export type PhaseActionError = {
  kind: PhaseActionErrorKind
  message: string
  currentRevision: number | null
  validation: ResearchPhaseValidationResponse | null
  detail: unknown
}

export type PhaseActionResult<T> =
  | { ok: true; data: T }
  | { ok: false; error: PhaseActionError }

export type PhaseConflictState = {
  message: string
  currentRevision: number | null
}

export function isPhaseRevisionConflict(detail: unknown): detail is ResearchPhaseConflictDetail {
  return typeof detail === 'object'
    && detail !== null
    && 'message' in detail
    && (detail as ResearchPhaseConflictDetail).message === 'Phase annotation set revision conflict.'
}

export function isPhaseValidationErrorDetail(detail: unknown): detail is ResearchPhaseValidationErrorDetail {
  return typeof detail === 'object'
    && detail !== null
    && 'message' in detail
    && typeof (detail as ResearchPhaseValidationErrorDetail).message === 'string'
}

export function isAnnotationSetReadOnly(status: ResearchPhaseAnnotationSetStatus | null | undefined) {
  return status === 'submitted' || status === 'reviewed' || status === 'locked'
}

export function restoreSelectedSegmentId(
  previousSegmentId: number | null,
  segments: readonly { id: number }[],
) {
  if (previousSegmentId === null) {
    return null
  }
  return segments.some((segment) => segment.id === previousSegmentId) ? previousSegmentId : null
}

async function readJsonSafely(response: Response) {
  try {
    return await response.json()
  } catch {
    return null
  }
}

function buildActionError(response: Response | null, detail: unknown, fallbackMessage: string): PhaseActionError {
  if (isPhaseRevisionConflict(detail)) {
    return {
      kind: 'conflict',
      message: detail.message,
      currentRevision: detail.current_revision ?? null,
      validation: null,
      detail,
    }
  }

  if (isPhaseValidationErrorDetail(detail)) {
    if (detail.message === 'Phase annotation set has warnings that require confirmation.') {
      return {
        kind: 'warning_confirmation',
        message: detail.message,
        currentRevision: null,
        validation: detail.validation ?? null,
        detail,
      }
    }

    if (detail.message === 'Phase annotation set has validation errors.') {
      return {
        kind: 'validation_error',
        message: detail.message,
        currentRevision: null,
        validation: detail.validation ?? null,
        detail,
      }
    }
  }

  if (typeof detail === 'string') {
    return {
      kind: 'business',
      message: detail,
      currentRevision: null,
      validation: null,
      detail,
    }
  }

  return {
    kind: response ? 'business' : 'network',
    message: fallbackMessage,
    currentRevision: null,
    validation: null,
    detail,
  }
}

function sortSegments(detail: ResearchPhaseAnnotationSetDetail): ResearchPhaseAnnotationSetDetail {
  return {
    ...detail,
    protocol: {
      ...detail.protocol,
      labels: detail.protocol.labels.slice().sort((left, right) => left.display_order - right.display_order || left.id - right.id),
    },
    segments: detail.segments.slice().sort((left, right) => left.start_frame - right.start_frame || left.id - right.id),
  }
}

async function requestJson<T>(
  path: string,
  init?: RequestInit,
): Promise<PhaseActionResult<T>> {
  try {
    const response = await fetch(apiUrl(path), init)
    if (!response.ok) {
      const payload = await readJsonSafely(response)
      const detail = payload?.detail ?? payload
      return {
        ok: false,
        error: buildActionError(response, detail, `Request failed: ${response.status}`),
      }
    }

    return {
      ok: true,
      data: await response.json() as T,
    }
  } catch (error) {
    return {
      ok: false,
      error: buildActionError(null, error, error instanceof Error ? error.message : 'Unknown network error'),
    }
  }
}

async function requestBlob(
  path: string,
): Promise<PhaseActionResult<{ blob: Blob; headers: Headers }>> {
  try {
    const response = await fetch(apiUrl(path), { cache: 'no-store' })
    if (!response.ok) {
      const payload = await readJsonSafely(response)
      const detail = payload?.detail ?? payload
      return {
        ok: false,
        error: buildActionError(response, detail, `Request failed: ${response.status}`),
      }
    }
    return {
      ok: true,
      data: {
        blob: await response.blob(),
        headers: response.headers,
      },
    }
  } catch (error) {
    return {
      ok: false,
      error: buildActionError(null, error, error instanceof Error ? error.message : 'Unknown network error'),
    }
  }
}

export const useResearchPhasesStore = defineStore('researchPhases', {
  state: () => ({
    protocols: [] as ResearchPhaseProtocolSummary[],
    protocolDetails: {} as Record<number, ResearchPhaseProtocolDetail>,
    selectedProtocolId: null as number | null,
    annotationSets: [] as ResearchPhaseAnnotationSetSummary[],
    currentAnnotationSet: null as ResearchPhaseAnnotationSetDetail | null,
    mappingProfiles: [] as ResearchPhaseLabelMappingProfileSummary[],
    mappingProfileDetails: {} as Record<number, ResearchPhaseLabelMappingProfileDetail>,
    loadingMappingProfiles: false,
    segments: [] as ResearchPhaseAnnotationSetDetail['segments'],
    validation: null as ResearchPhaseValidationResponse | null,
    loadingProtocols: false,
    loadingAnnotationSet: false,
    saving: false,
    validating: false,
    submitting: false,
    exporting: false,
    saveState: 'idle' as PhaseSaveState,
    errorMessage: '',
    conflictState: null as PhaseConflictState | null,
    activeVideoId: null as number | null,
    sessionToken: 0,
    exportKind: null as PhaseExportKind | null,
  }),
  getters: {
    isReadOnly(state) {
      return isAnnotationSetReadOnly(state.currentAnnotationSet?.status ?? null)
    },
  },
  actions: {
    startVideoSession(videoId: number) {
      this.activeVideoId = videoId
      this.sessionToken += 1
      this.annotationSets = []
      this.currentAnnotationSet = null
      this.mappingProfiles = []
      this.mappingProfileDetails = {}
      this.loadingMappingProfiles = false
      this.segments = []
      this.validation = null
      this.selectedProtocolId = null
      this.errorMessage = ''
      this.conflictState = null
      this.saveState = 'idle'
    },
    clearVideoState() {
      this.activeVideoId = null
      this.sessionToken += 1
      this.annotationSets = []
      this.currentAnnotationSet = null
      this.mappingProfiles = []
      this.mappingProfileDetails = {}
      this.loadingMappingProfiles = false
      this.segments = []
      this.validation = null
      this.selectedProtocolId = null
      this.errorMessage = ''
      this.conflictState = null
      this.saveState = 'idle'
    },
    setSaveState(nextState: PhaseSaveState, message = '') {
      this.saveState = nextState
      this.errorMessage = message
    },
    applyAnnotationSet(detail: ResearchPhaseAnnotationSetDetail) {
      const sortedDetail = sortSegments(detail)
      this.currentAnnotationSet = sortedDetail
      this.segments = sortedDetail.segments
      this.selectedProtocolId = sortedDetail.protocol_id
      const summary: ResearchPhaseAnnotationSetSummary = {
        id: sortedDetail.id,
        video_id: sortedDetail.video_id,
        protocol_id: sortedDetail.protocol_id,
        annotator_id: sortedDetail.annotator_id,
        status: sortedDetail.status,
        revision: sortedDetail.revision,
        submitted_at: sortedDetail.submitted_at,
        created_at: sortedDetail.created_at,
        updated_at: sortedDetail.updated_at,
        protocol_name: sortedDetail.protocol_name,
        protocol_version: sortedDetail.protocol_version,
        annotator_username: sortedDetail.annotator_username,
        segment_count: sortedDetail.segments.length,
        has_open_segment: sortedDetail.segments.some((segment) => segment.end_frame_exclusive === null),
      }
      this.annotationSets = [
        summary,
        ...this.annotationSets.filter((item) => item.id !== summary.id),
      ]
      this.protocolDetails[sortedDetail.protocol.id] = sortedDetail.protocol
    },
    handleActionError(error: PhaseActionError, options: { markSaving?: boolean } = {}) {
      if (error.kind === 'conflict') {
        this.conflictState = {
          message: error.message,
          currentRevision: error.currentRevision,
        }
        this.saveState = 'conflict'
      } else if (options.markSaving !== false) {
        this.saveState = 'error'
      }
      this.errorMessage = error.message
      if (error.validation) {
        this.validation = error.validation
      }
      return { ok: false, error } as const
    },
    requireCurrentAnnotationSet(): PhaseActionResult<ResearchPhaseAnnotationSetDetail> {
      if (!this.currentAnnotationSet) {
        return {
          ok: false,
          error: {
            kind: 'missing',
            message: 'Phase annotation set is not loaded.',
            currentRevision: null,
            validation: null,
            detail: null,
          },
        }
      }
      if (this.saveState === 'conflict') {
        return {
          ok: false,
          error: {
            kind: 'conflict',
            message: this.conflictState?.message ?? 'Phase annotation set revision conflict.',
            currentRevision: this.conflictState?.currentRevision ?? null,
            validation: null,
            detail: this.conflictState,
          },
        }
      }
      return { ok: true, data: this.currentAnnotationSet }
    },
    requireDraftAnnotationSet(): PhaseActionResult<ResearchPhaseAnnotationSetDetail> {
      const current = this.requireCurrentAnnotationSet()
      if (!current.ok) {
        return current
      }
      if (isAnnotationSetReadOnly(current.data.status)) {
        return {
          ok: false,
          error: {
            kind: 'readonly',
            message: 'Only draft phase annotation sets can be modified.',
            currentRevision: null,
            validation: null,
            detail: current.data.status,
          },
        }
      }
      if (current.data.status !== 'draft') {
        return {
          ok: false,
          error: {
            kind: 'readonly',
            message: 'Only draft phase annotation sets can be modified.',
            currentRevision: null,
            validation: null,
            detail: current.data.status,
          },
        }
      }
      return current
    },
    async fetchProtocols() {
      const sessionToken = this.sessionToken
      this.loadingProtocols = true
      this.errorMessage = ''
      const result = await requestJson<ResearchPhaseProtocolSummary[]>('/api/research/phase-protocols')
      if (sessionToken !== this.sessionToken) {
        this.loadingProtocols = false
        return result
      }
      if (!result.ok) {
        this.loadingProtocols = false
        return this.handleActionError(result.error, { markSaving: false })
      }
      this.protocols = result.data
      this.loadingProtocols = false
      return result
    },
    async fetchProtocol(protocolId: number) {
      const sessionToken = this.sessionToken
      const result = await requestJson<ResearchPhaseProtocolDetail>(`/api/research/phase-protocols/${protocolId}`)
      if (sessionToken !== this.sessionToken) {
        return result
      }
      if (!result.ok) {
        return this.handleActionError(result.error, { markSaving: false })
      }
      this.protocolDetails[protocolId] = result.data
      return result
    },
    async fetchVideoAnnotationSets(videoId: number) {
      const sessionToken = this.sessionToken
      const result = await requestJson<ResearchPhaseAnnotationSetSummary[]>(`/api/research/videos/${videoId}/phase-annotation-sets`)
      if (sessionToken !== this.sessionToken) {
        return result
      }
      if (!result.ok) {
        return this.handleActionError(result.error, { markSaving: false })
      }
      this.annotationSets = result.data
      return result
    },
    async getOrCreateAnnotationSet(videoId: number, protocolId: number, username: string) {
      const sessionToken = this.sessionToken
      this.loadingAnnotationSet = true
      this.errorMessage = ''
      const payload: CreateResearchPhaseAnnotationSetRequest = {
        protocol_id: protocolId,
        username,
      }
      const result = await requestJson<CreateResearchPhaseAnnotationSetResponse>(
        `/api/research/videos/${videoId}/phase-annotation-sets`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        },
      )
      if (sessionToken !== this.sessionToken) {
        this.loadingAnnotationSet = false
        return result
      }
      if (!result.ok) {
        this.loadingAnnotationSet = false
        return this.handleActionError(result.error, { markSaving: false })
      }
      this.applyAnnotationSet(result.data.annotation_set)
      this.loadingAnnotationSet = false
      return result
    },
    async fetchAnnotationSet(annotationSetId: number) {
      const sessionToken = this.sessionToken
      this.loadingAnnotationSet = true
      const result = await requestJson<ResearchPhaseAnnotationSetDetail>(`/api/research/phase-annotation-sets/${annotationSetId}`)
      if (sessionToken !== this.sessionToken) {
        this.loadingAnnotationSet = false
        return result
      }
      if (!result.ok) {
        this.loadingAnnotationSet = false
        return this.handleActionError(result.error, { markSaving: false })
      }
      this.applyAnnotationSet(result.data)
      this.loadingAnnotationSet = false
      return result
    },
    async applyMutationRequest(request: Promise<PhaseActionResult<ResearchPhaseMutationResponse>>) {
      this.saving = true
      this.setSaveState('saving')
      const result = await request
      this.saving = false
      if (!result.ok) {
        return this.handleActionError(result.error)
      }
      this.applyAnnotationSet(result.data.annotation_set)
      this.conflictState = null
      this.setSaveState('saved')
      return result
    },
    async createSegment(payload: Omit<CreateResearchPhaseSegmentRequest, 'expected_revision'>) {
      const current = this.requireDraftAnnotationSet()
      if (!current.ok) {
        return this.handleActionError(current.error)
      }
      return this.applyMutationRequest(requestJson<ResearchPhaseMutationResponse>(
        `/api/research/phase-annotation-sets/${current.data.id}/segments`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            ...payload,
            expected_revision: current.data.revision,
          } satisfies CreateResearchPhaseSegmentRequest),
        },
      ))
    },
    async transitionPhase(phaseLabelId: number, currentFrame: number) {
      const current = this.requireDraftAnnotationSet()
      if (!current.ok) {
        return this.handleActionError(current.error)
      }
      const payload: TransitionResearchPhaseRequest = {
        phase_label_id: phaseLabelId,
        current_frame: currentFrame,
        expected_revision: current.data.revision,
      }
      return this.applyMutationRequest(requestJson<ResearchPhaseMutationResponse>(
        `/api/research/phase-annotation-sets/${current.data.id}/transition`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        },
      ))
    },
    async closeActiveSegment(endFrameExclusive: number) {
      const current = this.requireDraftAnnotationSet()
      if (!current.ok) {
        return this.handleActionError(current.error)
      }
      const payload: CloseActivePhaseSegmentRequest = {
        end_frame_exclusive: endFrameExclusive,
        expected_revision: current.data.revision,
      }
      return this.applyMutationRequest(requestJson<ResearchPhaseMutationResponse>(
        `/api/research/phase-annotation-sets/${current.data.id}/close-active`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        },
      ))
    },
    async updateSegment(segmentId: number, patch: Omit<UpdateResearchPhaseSegmentRequest, 'expected_revision'>) {
      const current = this.requireDraftAnnotationSet()
      if (!current.ok) {
        return this.handleActionError(current.error)
      }
      return this.applyMutationRequest(requestJson<ResearchPhaseMutationResponse>(
        `/api/research/phase-segments/${segmentId}`,
        {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            ...patch,
            expected_revision: current.data.revision,
          } satisfies UpdateResearchPhaseSegmentRequest),
        },
      ))
    },
    async deleteSegment(segmentId: number) {
      const current = this.requireDraftAnnotationSet()
      if (!current.ok) {
        return this.handleActionError(current.error)
      }
      return this.applyMutationRequest(requestJson<ResearchPhaseMutationResponse>(
        `/api/research/phase-segments/${segmentId}?${new URLSearchParams({
          expected_revision: String(current.data.revision),
        }).toString()}`,
        {
          method: 'DELETE',
        },
      ))
    },
    async splitSegment(segmentId: number, splitFrame: number) {
      const current = this.requireDraftAnnotationSet()
      if (!current.ok) {
        return this.handleActionError(current.error)
      }
      const payload: SplitPhaseSegmentRequest = {
        split_frame: splitFrame,
        expected_revision: current.data.revision,
      }
      return this.applyMutationRequest(requestJson<ResearchPhaseMutationResponse>(
        `/api/research/phase-segments/${segmentId}/split`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        },
      ))
    },
    async mergeSegments(leftSegmentId: number, rightSegmentId: number) {
      const current = this.requireDraftAnnotationSet()
      if (!current.ok) {
        return this.handleActionError(current.error)
      }
      const payload: MergePhaseSegmentsRequest = {
        left_segment_id: leftSegmentId,
        right_segment_id: rightSegmentId,
        expected_revision: current.data.revision,
      }
      return this.applyMutationRequest(requestJson<ResearchPhaseMutationResponse>(
        `/api/research/phase-annotation-sets/${current.data.id}/merge`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        },
      ))
    },
    async validateAnnotationSet() {
      const current = this.requireCurrentAnnotationSet()
      if (!current.ok) {
        return this.handleActionError(current.error, { markSaving: false })
      }
      this.validating = true
      const result = await requestJson<ResearchPhaseValidationResponse>(
        `/api/research/phase-annotation-sets/${current.data.id}/validate`,
      )
      this.validating = false
      if (!result.ok) {
        return this.handleActionError(result.error, { markSaving: false })
      }
      this.validation = result.data
      return result
    },
    async submitAnnotationSet(confirmWarnings = false) {
      const current = this.requireCurrentAnnotationSet()
      if (!current.ok) {
        return this.handleActionError(current.error)
      }
      this.submitting = true
      this.setSaveState('saving')
      const payload: SubmitPhaseAnnotationSetRequest = {
        expected_revision: current.data.revision,
        confirm_warnings: confirmWarnings,
      }
      const result = await requestJson<ResearchPhaseStatusMutationResponse>(
        `/api/research/phase-annotation-sets/${current.data.id}/submit`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        },
      )
      this.submitting = false
      if (!result.ok) {
        if (result.error.kind !== 'warning_confirmation') {
          return this.handleActionError(result.error)
        }
        this.errorMessage = result.error.message
        if (result.error.validation) {
          this.validation = result.error.validation
        }
        this.saveState = 'saved'
        return result
      }
      this.applyAnnotationSet(result.data.annotation_set)
      this.validation = result.data.validation
      this.conflictState = null
      this.setSaveState('saved')
      return result
    },
    async reopenAnnotationSet() {
      const current = this.requireCurrentAnnotationSet()
      if (!current.ok) {
        return this.handleActionError(current.error)
      }
      this.submitting = true
      this.setSaveState('saving')
      const payload: ReopenPhaseAnnotationSetRequest = {
        expected_revision: current.data.revision,
      }
      const result = await requestJson<ResearchPhaseStatusMutationResponse>(
        `/api/research/phase-annotation-sets/${current.data.id}/reopen`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        },
      )
      this.submitting = false
      if (!result.ok) {
        return this.handleActionError(result.error)
      }
      this.applyAnnotationSet(result.data.annotation_set)
      this.conflictState = null
      this.setSaveState('saved')
      return result
    },
    async fetchMappingProfiles(protocolId: number, includeArchived = false) {
      this.loadingMappingProfiles = true
      const query = includeArchived ? '?include_archived=true' : ''
      const result = await requestJson<ResearchPhaseLabelMappingProfileSummary[]>(
        `/api/research/phase-protocols/${protocolId}/label-mapping-profiles${query}`,
      )
      this.loadingMappingProfiles = false
      if (!result.ok) {
        return this.handleActionError(result.error, { markSaving: false })
      }
      this.mappingProfiles = result.data
      return result
    },
    async fetchMappingProfile(profileId: number) {
      const result = await requestJson<ResearchPhaseLabelMappingProfileDetail>(
        `/api/research/phase-label-mapping-profiles/${profileId}`,
      )
      if (!result.ok) {
        return this.handleActionError(result.error, { markSaving: false })
      }
      this.mappingProfileDetails[profileId] = result.data
      return result
    },
    async createMappingProfile(protocolId: number, payload: CreateResearchPhaseLabelMappingProfileRequest) {
      const result = await requestJson<ResearchPhaseLabelMappingProfileDetail>(
        `/api/research/phase-protocols/${protocolId}/label-mapping-profiles`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        },
      )
      if (!result.ok) {
        return this.handleActionError(result.error, { markSaving: false })
      }
      this.mappingProfileDetails[result.data.id] = result.data
      await this.fetchMappingProfiles(protocolId, true)
      return result
    },
    async mergeMappingClasses(profileId: number, payload: MergeResearchPhaseMappingClassesRequest) {
      const result = await requestJson<ResearchPhaseLabelMappingProfileDetail>(
        `/api/research/phase-label-mapping-profiles/${profileId}/merge-classes`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        },
      )
      if (!result.ok) {
        return this.handleActionError(result.error, { markSaving: false })
      }
      this.mappingProfileDetails[profileId] = result.data
      await this.fetchMappingProfiles(result.data.protocol_id, true)
      return result
    },
    async unmergeMappingTarget(profileId: number, payload: UnmergeResearchPhaseMappingTargetRequest) {
      const result = await requestJson<ResearchPhaseLabelMappingProfileDetail>(
        `/api/research/phase-label-mapping-profiles/${profileId}/unmerge-target`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        },
      )
      if (!result.ok) {
        return this.handleActionError(result.error, { markSaving: false })
      }
      this.mappingProfileDetails[profileId] = result.data
      await this.fetchMappingProfiles(result.data.protocol_id, true)
      return result
    },
    async publishMappingProfile(profileId: number) {
      const result = await requestJson<ResearchPhaseLabelMappingProfileDetail>(
        `/api/research/phase-label-mapping-profiles/${profileId}/publish`,
        { method: 'POST' },
      )
      if (!result.ok) {
        return this.handleActionError(result.error, { markSaving: false })
      }
      this.mappingProfileDetails[profileId] = result.data
      await this.fetchMappingProfiles(result.data.protocol_id, true)
      return result
    },
    async duplicateMappingProfile(profileId: number, payload: DuplicateResearchPhaseLabelMappingProfileRequest) {
      const result = await requestJson<ResearchPhaseLabelMappingProfileDetail>(
        `/api/research/phase-label-mapping-profiles/${profileId}/duplicate`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        },
      )
      if (!result.ok) {
        return this.handleActionError(result.error, { markSaving: false })
      }
      this.mappingProfileDetails[result.data.id] = result.data
      await this.fetchMappingProfiles(result.data.protocol_id, true)
      return result
    },
    async archiveMappingProfile(profileId: number) {
      const result = await requestJson<ResearchPhaseLabelMappingProfileDetail>(
        `/api/research/phase-label-mapping-profiles/${profileId}/archive`,
        { method: 'POST' },
      )
      if (!result.ok) {
        return this.handleActionError(result.error, { markSaving: false })
      }
      this.mappingProfileDetails[profileId] = result.data
      await this.fetchMappingProfiles(result.data.protocol_id, true)
      return result
    },
    async downloadExport(kind: PhaseExportKind, options: { mappingProfileId?: number | null, fallbackFilename?: string | null } = {}) {
      const current = this.requireCurrentAnnotationSet()
      if (!current.ok) {
        return this.handleActionError(current.error, { markSaving: false })
      }
      const mappingQuery = kind === 'json' && options.mappingProfileId
        ? `?mapping_profile_id=${encodeURIComponent(String(options.mappingProfileId))}`
        : ''
      const pathByKind: Record<PhaseExportKind, string> = {
        json: `/api/research/phase-annotation-sets/${current.data.id}/export/json${mappingQuery}`,
        segments: `/api/research/phase-annotation-sets/${current.data.id}/export/segments`,
        framewise: `/api/research/phase-annotation-sets/${current.data.id}/export/framewise`,
      }
      this.exporting = true
      this.exportKind = kind
      const result = await requestBlob(pathByKind[kind])
      this.exporting = false
      this.exportKind = null
      if (!result.ok) {
        return this.handleActionError(result.error, { markSaving: false })
      }
      const filename = parseContentDispositionFilename(result.data.headers.get('Content-Disposition'))
        ?? options.fallbackFilename
        ?? `research-video-${current.data.video_id}.${kind === 'json' ? 'json' : 'csv'}`
      downloadBlobWithFilename({
        blob: result.data.blob,
        filename,
      })
      return {
        ok: true,
        data: {
          filename,
          validationErrors: Number.parseInt(result.data.headers.get('X-Phase-Validation-Errors') ?? '0', 10) || 0,
          validationWarnings: Number.parseInt(result.data.headers.get('X-Phase-Validation-Warnings') ?? '0', 10) || 0,
        },
      } as const
    },
    async downloadJson(options: { mappingProfileId?: number | null, fallbackFilename?: string | null } = {}) {
      return this.downloadExport('json', options)
    },
    async downloadSegmentCsv() {
      return this.downloadExport('segments')
    },
    async downloadFramewiseCsv() {
      return this.downloadExport('framewise')
    },
  },
})
