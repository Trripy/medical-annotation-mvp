import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import enUS from '../src/i18n/locales/en-US.ts'
import zhCN from '../src/i18n/locales/zh-CN.ts'

const phasePage = readFileSync(new URL('../src/views/ResearchVideoPhasePage.vue', import.meta.url), 'utf8')
const phaseStore = readFileSync(new URL('../src/stores/researchPhases.ts', import.meta.url), 'utf8')
const phaseTypes = readFileSync(new URL('../src/types/researchPhase.ts', import.meta.url), 'utf8')

test('phase gap fill button is scoped to draft original view with a unique idle key label', () => {
  assert.match(phasePage, /idlePhaseLabels[\s\S]*label\.key === 'idle'/)
  assert.doesNotMatch(phasePage, /phase_label_id\s*=\s*1/)
  assert.doesNotMatch(phasePage, /phaseLabelId\s*=\s*1/)
  assert.match(phasePage, /isMappedView\.value[\s\S]*phaseGapFill\.mappedViewDisabled/)
  assert.match(phasePage, /pendingPhaseDraft\.value[\s\S]*phaseGapFill\.pendingPhaseExists/)
  assert.match(phasePage, /openSegment\.value[\s\S]*phaseGapFill\.openSegmentExists/)
  assert.match(phasePage, /saving\.value \|\| saveState\.value === 'saving' \|\| saveState\.value === 'conflict'/)
  assert.doesNotMatch(phasePage, /saveState\.value === 'error'[\s\S]{0,120}phaseGapFill\.unsavedSegmentExists/)
  assert.match(phasePage, /canFillGapsWithIdle/)
  assert.match(phasePage, /phaseGapFill\.button/)
})

test('phase gap fill preview and fill use batch endpoints and never send gap ranges from the client', () => {
  assert.match(phaseStore, /async previewGapFill\(phaseLabelId: number\)/)
  assert.match(phaseStore, /\/fill-gaps\/preview/)
  assert.match(phaseStore, /async fillGaps\(phaseLabelId: number, expectedRevision: number\)/)
  assert.match(phaseStore, /\/fill-gaps/)
  assert.match(phaseStore, /expected_revision: expectedRevision/)
  assert.doesNotMatch(phaseStore, /start_frame: gap/)
  assert.doesNotMatch(phaseStore, /end_frame_exclusive: gap/)
  assert.doesNotMatch(phasePage, /createSegment\([^)]*gap/)
  assert.match(phaseTypes, /ResearchPhaseGapFillPreview/)
  assert.match(phaseTypes, /FillPhaseGapsRequest/)
})

test('phase gap fill dialog displays one-based inclusive ranges and updates after full annotation set response', () => {
  assert.match(phasePage, /function formatGapFillRange\(startFrame: number, endFrameExclusive: number\)/)
  assert.match(phasePage, /startFrame \+ 1/)
  assert.match(phasePage, /endFrameExclusive/)
  assert.match(phasePage, /openGapFillPreview/)
  assert.match(phasePage, /waitForPendingMutations\(\)/)
  assert.match(phasePage, /previewGapFill\(idlePhaseLabel\.value\.id\)/)
  assert.match(phasePage, /gapFillPreview\.value = result\.data/)
  assert.match(phasePage, /confirmGapFill/)
  assert.match(phasePage, /fillGaps\(preview\.phase_label_id, preview\.current_revision\)/)
  assert.match(phasePage, /validateAnnotationSet\(\)/)
  assert.match(phasePage, /phaseGapFill\.success/)
})

test('phase gap fill dialog uses readable scoped contrast for summary and gap rows', () => {
  assert.match(phasePage, /class="phase-gap-fill-dialog-shell"/)
  assert.match(phasePage, /--phase-gap-fill-text: #0f172a/)
  assert.match(phasePage, /--phase-gap-fill-muted: #334155/)
  assert.match(phasePage, /--phase-gap-fill-info-text: #0c4a6e/)
  assert.match(phasePage, /\.phase-gap-fill-summary strong[\s\S]*color: var\(--phase-gap-fill-text\)/)
  assert.match(phasePage, /\.phase-gap-fill-gap-row span[\s\S]*color: var\(--phase-gap-fill-muted\)/)
  assert.match(phasePage, /\.phase-gap-fill-description[\s\S]*color: var\(--phase-gap-fill-info-text\) !important/)
  assert.doesNotMatch(phasePage, /\.phase-gap-fill-dialog p[\s\S]{0,80}rgba\(226, 232, 240/)
  assert.doesNotMatch(phasePage, /\.phase-gap-fill-summary span[\s\S]{0,100}rgba\(148, 163, 184/)
  assert.doesNotMatch(phasePage, /\.phase-gap-fill-gap-row[\s\S]{0,160}rgba\(226, 232, 240/)
})

test('phase gap fill i18n key sets match and include required messages', () => {
  assert.deepEqual(Object.keys(zhCN.phaseGapFill).sort(), Object.keys(enUS.phaseGapFill).sort())
  assert.equal(zhCN.phaseGapFill.button, '填充空隙为 Idle')
  assert.equal(zhCN.phaseGapFill.idleLabelNotFound, '当前阶段协议中未找到唯一的空闲阶段标签。')
  assert.equal(enUS.phaseGapFill.button, 'Fill gaps with Idle')
})
