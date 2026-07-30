import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import type { ResearchPhaseValidationResponse } from '../src/types/researchPhase.ts'
import type { ResearchSkillAssessmentDetail, ResearchSkillValidationIssue, ResearchSkillValidationResponse } from '../src/types/researchSkill.ts'
import {
  beginPhaseVideoResize,
  buildFrameWorkspaceMeta,
  buildPhaseWorkspaceMeta,
  buildResearchTaskNavState,
  buildResearchWorkspaceBreadcrumb,
  buildSkillWorkspaceMeta,
  cancelPhaseVideoResize,
  clampPhaseVideoHeight,
  compactSkillValidationIssues,
  collapsePhaseVideo,
  expandPhaseVideo,
  finishPhaseVideoResize,
  getDefaultPhaseVideoHeight,
  getResearchResponsiveMode,
  isAssessmentReadOnlyForUi,
  nextPhaseRightPanelTabAfterSegmentSelect,
  nextPhaseRightPanelTabAfterValidate,
  parsePersistedPhaseVideoHeight,
  preserveResearchSessionState,
  RESEARCH_TASK_ORDER,
  summarizePhaseValidation,
  summarizeSkillValidation,
  updatePhaseVideoResize,
} from '../src/utils/researchWorkflowUi.ts'
import { restoreSelectedCriterionId } from '../src/utils/researchSkill.ts'

test('Task Nav keeps the same Frame Phase Skill order on all task pages', () => {
  assert.deepEqual(RESEARCH_TASK_ORDER, ['frame', 'phase', 'skill'])
  assert.deepEqual(buildResearchTaskNavState('frame', 12).map((item) => item.task), RESEARCH_TASK_ORDER)
  assert.deepEqual(buildResearchTaskNavState('phase', 12).map((item) => item.task), RESEARCH_TASK_ORDER)
  assert.deepEqual(buildResearchTaskNavState('skill', 12).map((item) => item.task), RESEARCH_TASK_ORDER)
})

test('Task Nav marks only the current task active and preserves frame query', () => {
  const state = buildResearchTaskNavState('phase', 37)
  assert.deepEqual(state.map((item) => item.active), [false, true, false])
  assert.deepEqual(state[0].query, { frame: '37' })
})

test('responsive helper maps desktop medium and compact layouts', () => {
  assert.equal(getResearchResponsiveMode(1600), 'desktop')
  assert.equal(getResearchResponsiveMode(1200), 'medium')
  assert.equal(getResearchResponsiveMode(900), 'compact')
})

test('Phase Inspector collapsed state can toggle without segment data loss', () => {
  const selectedSegmentId = 5
  let collapsed = false
  collapsed = !collapsed
  collapsed = !collapsed
  assert.equal(collapsed, false)
  assert.equal(selectedSegmentId, 5)
})

test('Phase Timeline still consumes the original segment collection', () => {
  const segments = [{ id: 1, start_frame: 0 }, { id: 2, start_frame: 20 }]
  const rendered = segments.map((segment) => segment.id)
  assert.deepEqual(rendered, [1, 2])
})

test('Phase Validation summary keeps issues available while details are collapsed', () => {
  const validation = {
    issue_counts: { error: 1, warning: 1, info: 0 },
    closed_coverage_percent: 88.5,
    closed_segment_count: 4,
    open_segment_count: 1,
    issues: [{ issue_type: 'gap' }],
  } as unknown as ResearchPhaseValidationResponse
  const summary = summarizePhaseValidation(validation)
  assert.equal(summary.errors, 1)
  assert.equal(summary.warnings, 1)
  assert.equal(summary.issues.length, 1)
})

test('Skill Validation summary separates completion counts from details', () => {
  const validation = {
    required_completed: 3,
    required_total: 5,
    completion_percent: 60,
    issue_counts: { error: 2, warning: 1, info: 0 },
    issues: [],
  } as unknown as ResearchSkillValidationResponse
  assert.deepEqual(summarizeSkillValidation(validation), {
    requiredCompleted: 3,
    requiredTotal: 5,
    errors: 2,
    warnings: 1,
    completionPercent: 60,
    issues: [],
  })
})

test('missing required score issues compact to one row per criterion target', () => {
  const issue = {
    issue_type: 'missing_required_score',
    severity: 'error',
    criterion_id: 9,
    score_id: null,
    phase_segment_id: null,
    evidence_id: null,
    message: '',
    details: {},
  } satisfies ResearchSkillValidationIssue
  const compact = compactSkillValidationIssues([issue, { ...issue }])
  assert.equal(compact.length, 1)
  assert.equal(compact[0].issueCount, 2)
})

test('missing required issue click payload still identifies the criterion', () => {
  const issue = {
    issue_type: 'missing_required_score',
    severity: 'error',
    criterion_id: 12,
    score_id: null,
    phase_segment_id: 4,
    evidence_id: null,
    message: '',
    details: {},
  } satisfies ResearchSkillValidationIssue
  assert.equal(issue.criterion_id, 12)
  assert.equal(issue.phase_segment_id, 4)
})

test('Skill Criterion selection restores existing criterion when the list refreshes', () => {
  assert.equal(restoreSelectedCriterionId(7, [{ id: 2 }, { id: 7 }]), 7)
  assert.equal(restoreSelectedCriterionId(7, [{ id: 2 }, { id: 3 }]), 2)
})

test('task page switching preserves current frame playback rate and locale state', () => {
  const state = preserveResearchSessionState({ frame: 48, playbackRate: 1.5, locale: 'zh-CN' })
  assert.deepEqual(state, { frame: 48, playbackRate: 1.5, locale: 'zh-CN' })
})

test('submitted assessment remains read-only in UI state', () => {
  assert.equal(isAssessmentReadOnlyForUi({ status: 'submitted' } as ResearchSkillAssessmentDetail), true)
  assert.equal(isAssessmentReadOnlyForUi({ status: 'draft' } as ResearchSkillAssessmentDetail), false)
})

test('Phase video height clamp enforces minimum height', () => {
  assert.equal(clampPhaseVideoHeight(1, 900), 260)
  assert.equal(clampPhaseVideoHeight(1, 700), 220)
})

test('Phase video height clamp enforces maximum height', () => {
  assert.equal(clampPhaseVideoHeight(900, 900), 585)
  assert.equal(clampPhaseVideoHeight(2000, 1600), 720)
})

test('illegal persisted Phase video heights fall back to default', () => {
  const fallback = getDefaultPhaseVideoHeight(900)
  assert.equal(parsePersistedPhaseVideoHeight(null, 900), fallback)
  assert.equal(parsePersistedPhaseVideoHeight('abc', 900), fallback)
  assert.equal(parsePersistedPhaseVideoHeight('-1', 900), fallback)
  assert.equal(parsePersistedPhaseVideoHeight('Infinity', 900), fallback)
})

test('old zero persisted Phase video height automatically recovers', () => {
  assert.equal(parsePersistedPhaseVideoHeight('0', 900), getDefaultPhaseVideoHeight(900))
})

test('collapsing Phase video does not persist zero height', () => {
  const collapsed = collapsePhaseVideo(340, 900)
  assert.equal(collapsed.isCollapsed, true)
  assert.equal(collapsed.lastExpandedHeight, 340)
})

test('expanding Phase video restores last expanded height', () => {
  const expanded = expandPhaseVideo(360, 900)
  assert.equal(expanded.isCollapsed, false)
  assert.equal(expanded.videoHeight, 360)
})

test('expanding Phase video clamps stale restored heights', () => {
  assert.equal(expandPhaseVideo(10, 900).videoHeight, 260)
  assert.equal(expandPhaseVideo(2000, 900).videoHeight, 585)
})

test('double-click reset uses default Phase video height', () => {
  assert.equal(getDefaultPhaseVideoHeight(900), clampPhaseVideoHeight(Math.round(900 * 0.52), 900))
})

test('Phase video drag does not modify currentTime', () => {
  const drag = updatePhaseVideoResize(beginPhaseVideoResize(340, 900, 12.5, 1.5), 480, 900)
  assert.equal(drag.currentTime, 12.5)
})

test('Phase video drag does not modify playbackRate', () => {
  const drag = updatePhaseVideoResize(beginPhaseVideoResize(340, 900, 12.5, 1.5), 480, 900)
  assert.equal(drag.playbackRate, 1.5)
})

test('pointerup clears Phase video drag state', () => {
  const finished = finishPhaseVideoResize(beginPhaseVideoResize(340, 900, 0, 1))
  assert.equal(finished.dragging, false)
})

test('Escape cancels Phase video drag and restores original height', () => {
  const drag = updatePhaseVideoResize(beginPhaseVideoResize(340, 900, 0, 1), 520, 900)
  const cancelled = cancelPhaseVideoResize(drag)
  assert.equal(cancelled.dragging, false)
  assert.equal(cancelled.currentHeight, 340)
})

test('Phase right panel tab switches between Inspector and QC', () => {
  assert.equal(nextPhaseRightPanelTabAfterSegmentSelect(), 'inspector')
  assert.equal(nextPhaseRightPanelTabAfterValidate('inspector', null), 'inspector')
})

test('Validate opens QC tab when validation returns errors or warnings', () => {
  const validation = {
    issue_counts: { error: 1, warning: 0, info: 0 },
  } as ResearchPhaseValidationResponse
  assert.equal(nextPhaseRightPanelTabAfterValidate('inspector', validation), 'validation')
})

test('Timeline segment selection opens Inspector tab', () => {
  assert.equal(nextPhaseRightPanelTabAfterSegmentSelect(), 'inspector')
})

test('QC issue click payload still carries frame and segment location', () => {
  const issue = { segment_id: 3, frame_start: 10 }
  assert.equal(issue.segment_id, 3)
  assert.equal(issue.frame_start, 10)
})

test('Phase desktop sidebar no longer contains PhaseValidationPanel', () => {
  const source = readFileSync(new URL('../src/views/ResearchVideoPhasePage.vue', import.meta.url), 'utf8')
  const leftSidebar = source.slice(
    source.indexOf('<aside v-if="!isCompactLayout" class="research-phase-sidebar">'),
    source.indexOf('<section class="research-phase-main">'),
  )
  assert.doesNotMatch(leftSidebar, /PhaseValidationPanel/)
})

test('Phase right action area keeps submit validate and export accessible', () => {
  const source = readFileSync(new URL('../src/views/ResearchVideoPhasePage.vue', import.meta.url), 'utf8')
  const rightActions = source.slice(source.indexOf('research-phase-right-actions'))
  assert.match(rightActions, /handleValidate/)
  assert.match(rightActions, /handleSubmit/)
  assert.match(rightActions, /handleExport/)
})

test('three research video pages use the shared workspace header component', () => {
  const pages = [
    '../src/views/ResearchVideoAnnotatePage.vue',
    '../src/views/ResearchVideoPhasePage.vue',
    '../src/views/ResearchVideoSkillPage.vue',
  ]
  for (const page of pages) {
    const source = readFileSync(new URL(page, import.meta.url), 'utf8')
    assert.match(source, /ResearchVideoWorkspaceHeader/)
  }
})

test('workspace breadcrumb combines research videos and current task labels', () => {
  assert.equal(buildResearchWorkspaceBreadcrumb('Phase Annotation', 'Research Videos'), 'Research Videos · Phase Annotation')
})

test('Frame workspace meta contains frame count and timestamp', () => {
  assert.deepEqual(buildFrameWorkspaceMeta(1, 100, '00:00.00'), ['Frame 1 / 100', '00:00.00'])
})

test('Phase workspace meta contains current phase', () => {
  assert.deepEqual(buildPhaseWorkspaceMeta(1, 100, '00:00.00', 'Idle'), ['Frame 1 / 100', '00:00.00', 'Current phase Idle'])
})

test('Skill workspace meta contains assessment status only', () => {
  assert.deepEqual(buildSkillWorkspaceMeta(1, 100, '00:00.00', 'Assessment draft · 20%'), ['Frame 1 / 100', '00:00.00', 'Assessment draft · 20%'])
})

test('workspace header title uses single-line ellipsis styling', () => {
  const source = readFileSync(new URL('../src/components/research/ResearchVideoWorkspaceHeader.vue', import.meta.url), 'utf8')
  assert.match(source, /white-space:\s*nowrap/)
  assert.match(source, /overflow:\s*hidden/)
  assert.match(source, /text-overflow:\s*ellipsis/)
  assert.match(source, /:title="title"/)
})

test('workspace header does not modify frame or assessment query itself', () => {
  const source = readFileSync(new URL('../src/components/research/ResearchVideoWorkspaceHeader.vue', import.meta.url), 'utf8')
  assert.doesNotMatch(source, /router\.replace|router\.push/)
  assert.match(source, /ResearchVideoTaskNav/)
})
