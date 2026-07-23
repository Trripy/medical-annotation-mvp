import { defineStore } from 'pinia'

import { apiUrl } from '../utils/api.ts'
import { downloadBlobWithFilename, parseContentDispositionFilename } from '../utils/download.ts'
import { isSkillAssessmentReadOnly, restoreSelectedScoreId } from '../utils/researchSkill.ts'
import type {
  CloneSkillRubricRequest,
  CreateSkillAssessmentRequest,
  CreateSkillAssessmentResponse,
  CreateSkillCriterionRequest,
  CreateSkillEvidenceRequest,
  CreateSkillRubricRequest,
  ResearchSkillAssessmentDetail,
  ResearchSkillAssessmentSummary,
  ResearchSkillConflictDetail,
  ResearchSkillCriterion,
  ResearchSkillMutationResponse,
  ResearchSkillRubricDetail,
  ResearchSkillRubricSummary,
  ResearchSkillScore,
  ResearchSkillStatusMutationResponse,
  ResearchSkillValidationErrorDetail,
  ResearchSkillValidationResponse,
  SubmitSkillAssessmentRequest,
  UpdateSkillAssessmentRequest,
  UpdateSkillCriterionRequest,
  UpdateSkillEvidenceRequest,
  UpdateSkillRubricRequest,
  UpsertSkillScoreRequest,
} from '../types/researchSkill.ts'

export type SkillSaveState = 'idle' | 'saving' | 'saved' | 'error' | 'conflict' | 'readonly'
export type SkillActionErrorKind =
  | 'conflict'
  | 'warning_confirmation'
  | 'validation_error'
  | 'business'
  | 'network'
  | 'readonly'
  | 'missing'

export type SkillActionError = {
  kind: SkillActionErrorKind
  message: string
  currentRevision: number | null
  validation: ResearchSkillValidationResponse | null
  detail: unknown
}

export type SkillActionResult<T> =
  | { ok: true; data: T }
  | { ok: false; error: SkillActionError }

export type SkillConflictState = {
  message: string
  currentRevision: number | null
}

type QueuedMutation<T> = {
  generation: number
  run: (latestRevision: number) => Promise<SkillActionResult<T>>
  resolve: (result: SkillActionResult<T>) => void
}

export function isSkillRevisionConflict(detail: unknown): detail is ResearchSkillConflictDetail {
  return typeof detail === 'object'
    && detail !== null
    && 'message' in detail
    && (detail as ResearchSkillConflictDetail).message === 'Skill assessment revision conflict.'
}

export function isSkillValidationErrorDetail(detail: unknown): detail is ResearchSkillValidationErrorDetail {
  return typeof detail === 'object'
    && detail !== null
    && 'message' in detail
    && typeof (detail as ResearchSkillValidationErrorDetail).message === 'string'
}

async function readJsonSafely(response: Response) {
  try {
    return await response.json()
  } catch {
    return null
  }
}

function buildActionError(response: Response | null, detail: unknown, fallbackMessage: string): SkillActionError {
  if (isSkillRevisionConflict(detail)) {
    return {
      kind: 'conflict',
      message: detail.message,
      currentRevision: detail.current_revision ?? null,
      validation: null,
      detail,
    }
  }
  if (isSkillValidationErrorDetail(detail)) {
    if (detail.message === 'Skill assessment has warnings that require confirmation.') {
      return {
        kind: 'warning_confirmation',
        message: detail.message,
        currentRevision: null,
        validation: detail.validation ?? null,
        detail,
      }
    }
    if (detail.message === 'Skill assessment has validation errors.') {
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

async function requestJson<T>(path: string, init?: RequestInit): Promise<SkillActionResult<T>> {
  try {
    const response = await fetch(apiUrl(path), init)
    if (!response.ok) {
      const payload = await readJsonSafely(response)
      const detail = payload?.detail ?? payload
      return { ok: false, error: buildActionError(response, detail, `Request failed: ${response.status}`) }
    }
    return { ok: true, data: await response.json() as T }
  } catch (error) {
    return {
      ok: false,
      error: buildActionError(null, error, error instanceof Error ? error.message : 'Unknown network error'),
    }
  }
}

async function requestBlob(path: string): Promise<SkillActionResult<{ blob: Blob; headers: Headers }>> {
  try {
    const response = await fetch(apiUrl(path), { cache: 'no-store' })
    if (!response.ok) {
      const payload = await readJsonSafely(response)
      const detail = payload?.detail ?? payload
      return { ok: false, error: buildActionError(response, detail, `Request failed: ${response.status}`) }
    }
    return { ok: true, data: { blob: await response.blob(), headers: response.headers } }
  } catch (error) {
    return {
      ok: false,
      error: buildActionError(null, error, error instanceof Error ? error.message : 'Unknown network error'),
    }
  }
}

function sortRubricDetail(detail: ResearchSkillRubricDetail): ResearchSkillRubricDetail {
  return {
    ...detail,
    criteria: detail.criteria.slice().sort((left, right) => left.display_order - right.display_order || left.id - right.id),
  }
}

function sortAssessmentDetail(detail: ResearchSkillAssessmentDetail): ResearchSkillAssessmentDetail {
  return {
    ...detail,
    rubric: sortRubricDetail(detail.rubric),
    phase_annotation_set: detail.phase_annotation_set
      ? {
        ...detail.phase_annotation_set,
        segments: detail.phase_annotation_set.segments.slice().sort((left, right) => left.start_frame - right.start_frame || left.id - right.id),
      }
      : null,
    scores: detail.scores
      .map((score) => ({
        ...score,
        evidence: score.evidence.slice().sort((left, right) => left.start_frame - right.start_frame || left.id - right.id),
      }))
      .sort((left, right) => {
        const leftCriterion = detail.rubric.criteria.find((criterion) => criterion.id === left.criterion_id)
        const rightCriterion = detail.rubric.criteria.find((criterion) => criterion.id === right.criterion_id)
        return (leftCriterion?.display_order ?? 0) - (rightCriterion?.display_order ?? 0)
          || left.target_key.localeCompare(right.target_key)
          || left.id - right.id
      }),
  }
}

export const useResearchSkillsStore = defineStore('researchSkills', {
  state: () => ({
    rubrics: [] as ResearchSkillRubricSummary[],
    selectedRubricId: null as number | null,
    selectedRubric: null as ResearchSkillRubricDetail | null,
    assessments: [] as ResearchSkillAssessmentSummary[],
    selectedAssessmentId: null as number | null,
    currentAssessment: null as ResearchSkillAssessmentDetail | null,
    selectedTargetType: 'overall' as 'overall' | 'phase_segment',
    selectedPhaseSegmentId: null as number | null,
    selectedCriterionId: null as number | null,
    selectedScoreId: null as number | null,
    selectedEvidenceId: null as number | null,
    validation: null as ResearchSkillValidationResponse | null,
    loadingRubrics: false,
    loadingRubric: false,
    loadingAssessments: false,
    loadingAssessment: false,
    saving: false,
    validating: false,
    submitting: false,
    exporting: false,
    managingRubric: false,
    saveState: 'idle' as SkillSaveState,
    errorMessage: '',
    conflictState: null as SkillConflictState | null,
    activeVideoId: null as number | null,
    sessionToken: 0,
    mutationQueue: [] as QueuedMutation<unknown>[],
    mutationQueueRunning: false,
    exportKind: null as 'json' | 'csv' | null,
  }),
  getters: {
    isReadOnly(state) {
      return isSkillAssessmentReadOnly(state.currentAssessment?.status ?? null)
    },
    selectedCriterion(state): ResearchSkillCriterion | null {
      return state.currentAssessment?.rubric.criteria.find((criterion) => criterion.id === state.selectedCriterionId) ?? null
    },
    selectedScore(state): ResearchSkillScore | null {
      if (state.selectedScoreId !== null) {
        return state.currentAssessment?.scores.find((score) => score.id === state.selectedScoreId) ?? null
      }
      if (!state.currentAssessment || !state.selectedCriterionId) {
        return null
      }
      const targetKey = state.selectedTargetType === 'overall' ? 'overall' : `segment:${state.selectedPhaseSegmentId}`
      return state.currentAssessment.scores.find((score) => score.criterion_id === state.selectedCriterionId && score.target_key === targetKey) ?? null
    },
  },
  actions: {
    startVideoSession(videoId: number) {
      this.sessionToken += 1
      this.activeVideoId = videoId
      this.clearQueue()
      this.rubrics = []
      this.selectedRubricId = null
      this.selectedRubric = null
      this.assessments = []
      this.clearAssessmentState()
      this.saveState = 'idle'
      this.errorMessage = ''
      this.conflictState = null
    },
    clearVideoState() {
      this.sessionToken += 1
      this.activeVideoId = null
      this.clearQueue()
      this.rubrics = []
      this.selectedRubricId = null
      this.selectedRubric = null
      this.assessments = []
      this.clearAssessmentState()
      this.saveState = 'idle'
      this.errorMessage = ''
      this.conflictState = null
    },
    clearAssessmentState() {
      this.selectedAssessmentId = null
      this.currentAssessment = null
      this.validation = null
      this.selectedTargetType = 'overall'
      this.selectedPhaseSegmentId = null
      this.selectedCriterionId = null
      this.selectedScoreId = null
      this.selectedEvidenceId = null
    },
    clearQueue() {
      this.mutationQueue = []
      this.mutationQueueRunning = false
    },
    setSaveState(nextState: SkillSaveState) {
      this.saveState = this.isReadOnly && nextState !== 'conflict' && nextState !== 'error' ? 'readonly' : nextState
    },
    applyRubric(detail: ResearchSkillRubricDetail) {
      const sorted = sortRubricDetail(detail)
      this.selectedRubric = sorted
      this.selectedRubricId = sorted.id
      this.rubrics = [
        ...this.rubrics.filter((rubric) => rubric.id !== sorted.id),
        {
          id: sorted.id,
          name: sorted.name,
          version: sorted.version,
          description: sorted.description,
          status: sorted.status,
          phase_protocol_id: sorted.phase_protocol_id,
          created_by_id: sorted.created_by_id,
          criterion_count: sorted.criteria.length,
          created_at: sorted.created_at,
          updated_at: sorted.updated_at,
        },
      ].sort((left, right) => left.name.localeCompare(right.name) || right.version - left.version || left.id - right.id)
    },
    applyAssessment(detail: ResearchSkillAssessmentDetail) {
      const sorted = sortAssessmentDetail(detail)
      const previousScoreId = this.selectedScoreId
      this.currentAssessment = sorted
      this.selectedAssessmentId = sorted.id
      this.selectedRubricId = sorted.rubric_id
      this.selectedRubric = sorted.rubric
      this.selectedScoreId = restoreSelectedScoreId(previousScoreId, sorted.scores)
      if (this.isReadOnly) {
        this.clearQueue()
        this.saveState = 'readonly'
      }
    },
    handleActionError(error: SkillActionError): SkillActionResult<never> {
      this.errorMessage = error.message
      if (error.kind === 'conflict') {
        this.conflictState = { message: error.message, currentRevision: error.currentRevision }
        this.clearQueue()
        this.saveState = 'conflict'
      } else {
        this.saveState = error.kind === 'readonly' ? 'readonly' : 'error'
      }
      return { ok: false, error }
    },
    missingError(message: string): SkillActionResult<never> {
      return this.handleActionError({ kind: 'missing', message, currentRevision: null, validation: null, detail: null })
    },
    requireCurrentAssessment(): SkillActionResult<ResearchSkillAssessmentDetail> {
      if (!this.currentAssessment) {
        return this.missingError('Skill assessment is not loaded.')
      }
      return { ok: true, data: this.currentAssessment }
    },
    requireDraftAssessment(): SkillActionResult<ResearchSkillAssessmentDetail> {
      const current = this.requireCurrentAssessment()
      if (!current.ok) {
        return current
      }
      if (isSkillAssessmentReadOnly(current.data.status)) {
        return this.handleActionError({
          kind: 'readonly',
          message: 'Only draft skill assessments can be modified.',
          currentRevision: null,
          validation: null,
          detail: null,
        })
      }
      if (this.saveState === 'conflict') {
        return this.handleActionError({
          kind: 'conflict',
          message: 'Skill assessment revision conflict.',
          currentRevision: this.conflictState?.currentRevision ?? null,
          validation: null,
          detail: this.conflictState,
        })
      }
      return current
    },
    async fetchRubrics(options: { includeArchived?: boolean } = {}) {
      this.loadingRubrics = true
      const params = new URLSearchParams()
      if (options.includeArchived) {
        params.set('include_archived', 'true')
      }
      const result = await requestJson<ResearchSkillRubricSummary[]>(`/api/research/skill-rubrics${params.size ? `?${params}` : ''}`, { cache: 'no-store' })
      this.loadingRubrics = false
      if (!result.ok) {
        return this.handleActionError(result.error)
      }
      this.rubrics = result.data
      return result
    },
    async fetchRubric(rubricId: number) {
      this.loadingRubric = true
      const result = await requestJson<ResearchSkillRubricDetail>(`/api/research/skill-rubrics/${rubricId}`, { cache: 'no-store' })
      this.loadingRubric = false
      if (!result.ok) {
        return this.handleActionError(result.error)
      }
      this.applyRubric(result.data)
      return result
    },
    async createRubric(payload: CreateSkillRubricRequest) {
      this.managingRubric = true
      const result = await requestJson<ResearchSkillRubricDetail>('/api/research/skill-rubrics', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      this.managingRubric = false
      if (!result.ok) {
        return this.handleActionError(result.error)
      }
      this.applyRubric(result.data)
      return result
    },
    async updateRubric(rubricId: number, payload: UpdateSkillRubricRequest) {
      this.managingRubric = true
      const result = await requestJson<ResearchSkillRubricDetail>(`/api/research/skill-rubrics/${rubricId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      this.managingRubric = false
      if (!result.ok) {
        return this.handleActionError(result.error)
      }
      this.applyRubric(result.data)
      return result
    },
    async cloneRubric(rubricId: number, payload: CloneSkillRubricRequest = {}) {
      this.managingRubric = true
      const result = await requestJson<ResearchSkillRubricDetail>(`/api/research/skill-rubrics/${rubricId}/clone`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      this.managingRubric = false
      if (!result.ok) {
        return this.handleActionError(result.error)
      }
      this.applyRubric(result.data)
      return result
    },
    async activateRubric(rubricId: number) {
      this.managingRubric = true
      const result = await requestJson<{ rubric: ResearchSkillRubricDetail }>(`/api/research/skill-rubrics/${rubricId}/activate`, { method: 'POST' })
      this.managingRubric = false
      if (!result.ok) {
        return this.handleActionError(result.error)
      }
      this.applyRubric(result.data.rubric)
      return result
    },
    async archiveRubric(rubricId: number) {
      this.managingRubric = true
      const result = await requestJson<{ rubric: ResearchSkillRubricDetail }>(`/api/research/skill-rubrics/${rubricId}/archive`, { method: 'POST' })
      this.managingRubric = false
      if (!result.ok) {
        return this.handleActionError(result.error)
      }
      this.applyRubric(result.data.rubric)
      return result
    },
    async createCriterion(rubricId: number, payload: CreateSkillCriterionRequest) {
      this.managingRubric = true
      const result = await requestJson<ResearchSkillCriterion>(`/api/research/skill-rubrics/${rubricId}/criteria`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      this.managingRubric = false
      if (!result.ok) {
        return this.handleActionError(result.error)
      }
      await this.fetchRubric(rubricId)
      return result
    },
    async updateCriterion(criterionId: number, payload: UpdateSkillCriterionRequest) {
      this.managingRubric = true
      const result = await requestJson<ResearchSkillCriterion>(`/api/research/skill-criteria/${criterionId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      this.managingRubric = false
      if (!result.ok) {
        return this.handleActionError(result.error)
      }
      if (result.data.rubric_id) {
        await this.fetchRubric(result.data.rubric_id)
      }
      return result
    },
    async fetchVideoAssessments(videoId: number) {
      this.loadingAssessments = true
      const result = await requestJson<ResearchSkillAssessmentSummary[]>(`/api/research/videos/${videoId}/skill-assessments`, { cache: 'no-store' })
      this.loadingAssessments = false
      if (!result.ok) {
        return this.handleActionError(result.error)
      }
      this.assessments = result.data
      return result
    },
    async getOrCreateAssessment(videoId: number, payload: CreateSkillAssessmentRequest) {
      const result = await requestJson<CreateSkillAssessmentResponse>(`/api/research/videos/${videoId}/skill-assessments`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (!result.ok) {
        return this.handleActionError(result.error)
      }
      this.applyAssessment(result.data.assessment)
      await this.fetchVideoAssessments(videoId)
      return result
    },
    async fetchAssessment(assessmentId: number, options: { generation?: number } = {}) {
      this.loadingAssessment = true
      const generation = options.generation ?? this.sessionToken
      const result = await requestJson<ResearchSkillAssessmentDetail>(`/api/research/skill-assessments/${assessmentId}`, { cache: 'no-store' })
      this.loadingAssessment = false
      if (generation !== this.sessionToken) {
        return result
      }
      if (!result.ok) {
        return this.handleActionError(result.error)
      }
      this.applyAssessment(result.data)
      return result
    },
    async selectAssessment(assessmentId: number) {
      this.sessionToken += 1
      this.clearQueue()
      this.clearAssessmentState()
      return this.fetchAssessment(assessmentId, { generation: this.sessionToken })
    },
    async reloadLatestAssessment() {
      if (!this.selectedAssessmentId) {
        return this.missingError('Skill assessment is not selected.')
      }
      const selectedScoreId = this.selectedScoreId
      const result = await this.fetchAssessment(this.selectedAssessmentId)
      if (result.ok) {
        this.selectedScoreId = restoreSelectedScoreId(selectedScoreId, this.currentAssessment?.scores ?? [])
        await this.validateAssessment()
        this.conflictState = null
        this.saveState = this.isReadOnly ? 'readonly' : 'saved'
      }
      return result
    },
    enqueueAssessmentMutation<T>(operation: (latestRevision: number) => Promise<SkillActionResult<T>>) {
      const draft = this.requireDraftAssessment()
      if (!draft.ok) {
        return Promise.resolve(draft as SkillActionResult<T>)
      }
      const generation = this.sessionToken
      return new Promise<SkillActionResult<T>>((resolve) => {
        this.mutationQueue.push({ generation, run: operation, resolve } as QueuedMutation<unknown>)
        void this.drainMutationQueue()
      })
    },
    async drainMutationQueue() {
      if (this.mutationQueueRunning) {
        return
      }
      this.mutationQueueRunning = true
      while (this.mutationQueue.length > 0) {
        const next = this.mutationQueue.shift()
        if (!next) {
          continue
        }
        if (next.generation !== this.sessionToken || !this.currentAssessment) {
          next.resolve({ ok: false, error: buildActionError(null, null, 'Stale skill assessment mutation ignored.') })
          continue
        }
        if (this.isReadOnly || this.saveState === 'conflict') {
          next.resolve(this.handleActionError({
            kind: this.saveState === 'conflict' ? 'conflict' : 'readonly',
            message: this.saveState === 'conflict' ? 'Skill assessment revision conflict.' : 'Only draft skill assessments can be modified.',
            currentRevision: this.conflictState?.currentRevision ?? null,
            validation: null,
            detail: null,
          }))
          this.mutationQueue = []
          break
        }
        this.saving = true
        this.setSaveState('saving')
        const result = await next.run(this.currentAssessment.revision)
        this.saving = false
        if (next.generation !== this.sessionToken) {
          next.resolve(result)
          continue
        }
        if (!result.ok) {
          next.resolve(this.handleActionError(result.error))
          if (result.error.kind === 'conflict') {
            this.mutationQueue = []
          }
          break
        }
        this.setSaveState('saved')
        next.resolve(result)
      }
      this.mutationQueueRunning = false
    },
    async updateAssessment(payload: Omit<UpdateSkillAssessmentRequest, 'expected_revision'>) {
      return this.enqueueAssessmentMutation<ResearchSkillMutationResponse>(async (latestRevision) => {
        const current = this.currentAssessment
        if (!current) {
          return this.missingError('Skill assessment is not loaded.')
        }
        const result = await requestJson<ResearchSkillMutationResponse>(`/api/research/skill-assessments/${current.id}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ...payload, expected_revision: latestRevision }),
        })
        if (result.ok) {
          this.applyAssessment(result.data.assessment)
        }
        return result
      })
    },
    async upsertScore(criterionId: number, payload: Omit<UpsertSkillScoreRequest, 'expected_revision'>) {
      return this.enqueueAssessmentMutation<ResearchSkillMutationResponse>(async (latestRevision) => {
        const current = this.currentAssessment
        if (!current) {
          return this.missingError('Skill assessment is not loaded.')
        }
        const result = await requestJson<ResearchSkillMutationResponse>(`/api/research/skill-assessments/${current.id}/scores/${criterionId}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ...payload, expected_revision: latestRevision }),
        })
        if (result.ok) {
          this.applyAssessment(result.data.assessment)
          this.selectedScoreId = result.data.created_score_ids[0] ?? result.data.changed_score_ids[0] ?? this.selectedScoreId
        }
        return result
      })
    },
    async deleteScore(scoreId: number) {
      return this.enqueueAssessmentMutation<ResearchSkillMutationResponse>(async (latestRevision) => {
        const result = await requestJson<ResearchSkillMutationResponse>(`/api/research/skill-scores/${scoreId}?expected_revision=${latestRevision}`, { method: 'DELETE' })
        if (result.ok) {
          this.applyAssessment(result.data.assessment)
          if (result.data.deleted_score_ids.includes(scoreId)) {
            this.selectedScoreId = null
          }
        }
        return result
      })
    },
    async createEvidence(scoreId: number, payload: Omit<CreateSkillEvidenceRequest, 'expected_revision'>) {
      return this.enqueueAssessmentMutation<ResearchSkillMutationResponse>(async (latestRevision) => {
        const result = await requestJson<ResearchSkillMutationResponse>(`/api/research/skill-scores/${scoreId}/evidence`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ...payload, expected_revision: latestRevision }),
        })
        if (result.ok) {
          this.applyAssessment(result.data.assessment)
          this.selectedEvidenceId = result.data.created_evidence_ids[0] ?? this.selectedEvidenceId
        }
        return result
      })
    },
    async updateEvidence(evidenceId: number, payload: Omit<UpdateSkillEvidenceRequest, 'expected_revision'>) {
      return this.enqueueAssessmentMutation<ResearchSkillMutationResponse>(async (latestRevision) => {
        const result = await requestJson<ResearchSkillMutationResponse>(`/api/research/skill-evidence/${evidenceId}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ...payload, expected_revision: latestRevision }),
        })
        if (result.ok) {
          this.applyAssessment(result.data.assessment)
        }
        return result
      })
    },
    async deleteEvidence(evidenceId: number) {
      return this.enqueueAssessmentMutation<ResearchSkillMutationResponse>(async (latestRevision) => {
        const result = await requestJson<ResearchSkillMutationResponse>(`/api/research/skill-evidence/${evidenceId}?expected_revision=${latestRevision}`, { method: 'DELETE' })
        if (result.ok) {
          this.applyAssessment(result.data.assessment)
          if (result.data.deleted_evidence_ids.includes(evidenceId)) {
            this.selectedEvidenceId = null
          }
        }
        return result
      })
    },
    async validateAssessment() {
      const current = this.requireCurrentAssessment()
      if (!current.ok) {
        return current as SkillActionResult<ResearchSkillValidationResponse>
      }
      this.validating = true
      const result = await requestJson<ResearchSkillValidationResponse>(`/api/research/skill-assessments/${current.data.id}/validate`, { cache: 'no-store' })
      this.validating = false
      if (!result.ok) {
        return this.handleActionError(result.error)
      }
      this.validation = result.data
      return result
    },
    async submitAssessment(confirmWarnings = false) {
      const current = this.requireCurrentAssessment()
      if (!current.ok) {
        return current as SkillActionResult<ResearchSkillStatusMutationResponse>
      }
      this.submitting = true
      const payload: SubmitSkillAssessmentRequest = {
        expected_revision: current.data.revision,
        confirm_warnings: confirmWarnings,
      }
      const result = await requestJson<ResearchSkillStatusMutationResponse>(`/api/research/skill-assessments/${current.data.id}/submit`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      this.submitting = false
      if (!result.ok) {
        if (result.error.validation) {
          this.validation = result.error.validation
        }
        if (result.error.kind === 'warning_confirmation') {
          return result
        }
        return this.handleActionError(result.error)
      }
      this.applyAssessment(result.data.assessment)
      this.validation = result.data.validation
      this.clearQueue()
      this.saveState = 'readonly'
      return result
    },
    async reopenAssessment() {
      const current = this.requireCurrentAssessment()
      if (!current.ok) {
        return current as SkillActionResult<ResearchSkillStatusMutationResponse>
      }
      this.submitting = true
      const result = await requestJson<ResearchSkillStatusMutationResponse>(`/api/research/skill-assessments/${current.data.id}/reopen`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ expected_revision: current.data.revision }),
      })
      this.submitting = false
      if (!result.ok) {
        return this.handleActionError(result.error)
      }
      this.applyAssessment(result.data.assessment)
      this.conflictState = null
      this.saveState = 'saved'
      await this.validateAssessment()
      return result
    },
    async downloadExport(kind: 'json' | 'csv') {
      const current = this.requireCurrentAssessment()
      if (!current.ok) {
        return current as SkillActionResult<{ filename: string }>
      }
      this.exporting = true
      this.exportKind = kind
      const result = await requestBlob(`/api/research/skill-assessments/${current.data.id}/export/${kind}`)
      this.exporting = false
      this.exportKind = null
      if (!result.ok) {
        return this.handleActionError(result.error)
      }
      const filename = parseContentDispositionFilename(result.data.headers.get('Content-Disposition'))
        ?? `skill-assessment-${current.data.id}.${kind}`
      downloadBlobWithFilename({ blob: result.data.blob, filename })
      return { ok: true, data: { filename } } as const
    },
    downloadJson() {
      return this.downloadExport('json')
    },
    downloadCsv() {
      return this.downloadExport('csv')
    },
  },
})
