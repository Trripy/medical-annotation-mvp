import type { ResearchPhaseValidationResponse } from '../types/researchPhase.ts'
import type {
  ResearchSkillAssessmentDetail,
  ResearchSkillValidationIssue,
  ResearchSkillValidationResponse,
} from '../types/researchSkill.ts'

export type ResearchTaskKey = 'frame' | 'phase' | 'skill'
export type ResearchResponsiveMode = 'desktop' | 'medium' | 'compact'
export type PhaseRightPanelTab = 'inspector' | 'validation'
export type PhaseVideoResizeState = {
  dragging: boolean
  originalHeight: number
  currentHeight: number
  currentTime: number
  playbackRate: number
}

export const RESEARCH_TASK_ORDER: ResearchTaskKey[] = ['frame', 'phase', 'skill']
export const PHASE_VIDEO_MIN_HEIGHT_DESKTOP = 260
export const PHASE_VIDEO_MIN_HEIGHT_LAPTOP = 220
export const PHASE_VIDEO_MAX_HEIGHT = 720
export const PHASE_VIDEO_DEFAULT_HEIGHT_RATIO = 0.52
export const PHASE_VIDEO_MAX_HEIGHT_RATIO = 0.65

export function buildResearchTaskNavState(activeTask: ResearchTaskKey, currentFrameIndex: number) {
  const query = currentFrameIndex >= 0 ? { frame: String(currentFrameIndex) } : {}
  return RESEARCH_TASK_ORDER.map((task) => ({
    task,
    active: task === activeTask,
    query,
  }))
}

export function getResearchResponsiveMode(width: number): ResearchResponsiveMode {
  if (width < 1024) return 'compact'
  if (width < 1440) return 'medium'
  return 'desktop'
}

export function summarizePhaseValidation(validation: ResearchPhaseValidationResponse | null) {
  return {
    errors: validation?.issue_counts.error ?? 0,
    warnings: validation?.issue_counts.warning ?? 0,
    coveragePercent: validation?.closed_coverage_percent ?? 0,
    closedSegments: validation?.closed_segment_count ?? 0,
    openSegments: validation?.open_segment_count ?? 0,
    issues: validation?.issues ?? [],
  }
}

export function getPhaseVideoMinimumHeight(workspaceHeight: number): number {
  return workspaceHeight < 760 ? PHASE_VIDEO_MIN_HEIGHT_LAPTOP : PHASE_VIDEO_MIN_HEIGHT_DESKTOP
}

export function getPhaseVideoMaximumHeight(workspaceHeight: number, minimumHeight = getPhaseVideoMinimumHeight(workspaceHeight)): number {
  const boundedWorkspaceHeight = Math.max(0, workspaceHeight)
  return Math.max(
    minimumHeight,
    Math.min(Math.round(boundedWorkspaceHeight * PHASE_VIDEO_MAX_HEIGHT_RATIO), PHASE_VIDEO_MAX_HEIGHT),
  )
}

export function clampPhaseVideoHeight(
  requestedHeight: number,
  workspaceHeight: number,
  minimumHeight = getPhaseVideoMinimumHeight(workspaceHeight),
): number {
  const maximumHeight = getPhaseVideoMaximumHeight(workspaceHeight, minimumHeight)
  const normalized = Number.isFinite(requestedHeight) ? requestedHeight : getDefaultPhaseVideoHeight(workspaceHeight, minimumHeight)
  return Math.max(minimumHeight, Math.min(Math.round(normalized), maximumHeight))
}

export function getDefaultPhaseVideoHeight(
  workspaceHeight: number,
  minimumHeight = getPhaseVideoMinimumHeight(workspaceHeight),
): number {
  return clampPhaseVideoHeight(Math.round(Math.max(0, workspaceHeight) * PHASE_VIDEO_DEFAULT_HEIGHT_RATIO), workspaceHeight, minimumHeight)
}

export function parsePersistedPhaseVideoHeight(rawValue: string | null, workspaceHeight: number): number {
  const minimumHeight = getPhaseVideoMinimumHeight(workspaceHeight)
  const parsed = rawValue === null ? Number.NaN : Number.parseInt(rawValue, 10)
  const maximumHeight = getPhaseVideoMaximumHeight(workspaceHeight, minimumHeight)
  if (!Number.isFinite(parsed) || parsed < minimumHeight || parsed > maximumHeight) {
    return getDefaultPhaseVideoHeight(workspaceHeight, minimumHeight)
  }
  return clampPhaseVideoHeight(parsed, workspaceHeight, minimumHeight)
}

export function collapsePhaseVideo(currentHeight: number, workspaceHeight: number) {
  return {
    isCollapsed: true,
    lastExpandedHeight: clampPhaseVideoHeight(currentHeight, workspaceHeight),
  }
}

export function expandPhaseVideo(lastExpandedHeight: number, workspaceHeight: number) {
  return {
    isCollapsed: false,
    videoHeight: clampPhaseVideoHeight(lastExpandedHeight, workspaceHeight),
  }
}

export function beginPhaseVideoResize(
  currentHeight: number,
  workspaceHeight: number,
  currentTime: number,
  playbackRate: number,
): PhaseVideoResizeState {
  const height = clampPhaseVideoHeight(currentHeight, workspaceHeight)
  return {
    dragging: true,
    originalHeight: height,
    currentHeight: height,
    currentTime,
    playbackRate,
  }
}

export function updatePhaseVideoResize(
  state: PhaseVideoResizeState,
  requestedHeight: number,
  workspaceHeight: number,
): PhaseVideoResizeState {
  return {
    ...state,
    currentHeight: clampPhaseVideoHeight(requestedHeight, workspaceHeight),
  }
}

export function finishPhaseVideoResize(state: PhaseVideoResizeState): PhaseVideoResizeState {
  return {
    ...state,
    dragging: false,
  }
}

export function cancelPhaseVideoResize(state: PhaseVideoResizeState): PhaseVideoResizeState {
  return {
    ...state,
    dragging: false,
    currentHeight: state.originalHeight,
  }
}

export function nextPhaseRightPanelTabAfterValidate(
  currentTab: PhaseRightPanelTab,
  validation: ResearchPhaseValidationResponse | null,
): PhaseRightPanelTab {
  if (!validation || validation.issue_counts.error + validation.issue_counts.warning <= 0) {
    return currentTab
  }
  return 'validation'
}

export function nextPhaseRightPanelTabAfterSegmentSelect(): PhaseRightPanelTab {
  return 'inspector'
}

export function summarizeSkillValidation(validation: ResearchSkillValidationResponse | null) {
  return {
    requiredCompleted: validation?.required_completed ?? 0,
    requiredTotal: validation?.required_total ?? 0,
    errors: validation?.issue_counts.error ?? 0,
    warnings: validation?.issue_counts.warning ?? 0,
    completionPercent: validation?.completion_percent ?? 0,
    issues: validation?.issues ?? [],
  }
}

export function compactSkillValidationIssues(issues: readonly ResearchSkillValidationIssue[]) {
  const grouped = new Map<string, ResearchSkillValidationIssue & { issueCount: number }>()
  for (const issue of issues) {
    const key = [
      issue.issue_type,
      issue.criterion_id ?? 'criterion:none',
      issue.phase_segment_id ?? 'segment:none',
      issue.score_id ?? 'score:none',
      issue.evidence_id ?? 'evidence:none',
    ].join('|')
    const existing = grouped.get(key)
    if (existing) {
      existing.issueCount += 1
    } else {
      grouped.set(key, { ...issue, issueCount: 1 })
    }
  }
  return [...grouped.values()]
}

export function preserveResearchSessionState<T extends {
  frame: number
  playbackRate: number
  locale: string
}>(state: T): T {
  return { ...state }
}

export function buildResearchWorkspaceBreadcrumb(taskLabel: string, researchVideosLabel: string) {
  return `${researchVideosLabel} · ${taskLabel}`
}

export function buildFrameWorkspaceMeta(frameNumber: number, totalFrames: number, timestamp: string) {
  return [`Frame ${frameNumber} / ${totalFrames}`, timestamp]
}

export function buildPhaseWorkspaceMeta(frameNumber: number, totalFrames: number, timestamp: string, currentPhase: string) {
  return [`Frame ${frameNumber} / ${totalFrames}`, timestamp, `Current phase ${currentPhase}`]
}

export function buildSkillWorkspaceMeta(frameNumber: number, totalFrames: number, timestamp: string, assessmentStatus: string) {
  return [`Frame ${frameNumber} / ${totalFrames}`, timestamp, assessmentStatus]
}

export function isAssessmentReadOnlyForUi(assessment: Pick<ResearchSkillAssessmentDetail, 'status'> | null) {
  return assessment?.status === 'submitted' || assessment?.status === 'reviewed' || assessment?.status === 'locked'
}
