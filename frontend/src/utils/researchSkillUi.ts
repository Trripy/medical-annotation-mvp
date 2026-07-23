import type { ResearchSkillCriterion, ResearchSkillEvidence, ResearchSkillPhaseSegment } from '../types/researchSkill.ts'

export function formatSkillFrame(frameIndex: number | null | undefined) {
  return frameIndex === null || frameIndex === undefined ? '' : `Frame ${frameIndex + 1}`
}

export function formatSkillFrameRange(startFrame: number, endFrameExclusive: number | null) {
  if (endFrameExclusive === null) {
    return `${formatSkillFrame(startFrame)} onward`
  }
  return `Frames ${startFrame + 1}-${endFrameExclusive}`
}

export function formatEvidenceRange(evidence: Pick<ResearchSkillEvidence, 'start_frame' | 'end_frame_exclusive'>) {
  if (evidence.end_frame_exclusive === null) {
    return `Frame ${evidence.start_frame + 1}`
  }
  return `Frames ${evidence.start_frame + 1}-${evidence.end_frame_exclusive}`
}

export function formatSkillTime(frameIndex: number, fps: number | null | undefined) {
  if (!fps || fps <= 0) {
    return '--:--'
  }
  const totalSeconds = Math.max(0, frameIndex / fps)
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = Math.floor(totalSeconds % 60)
  const centiseconds = Math.floor((totalSeconds % 1) * 100)
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}.${String(centiseconds).padStart(2, '0')}`
}

export function criterionTypeLabel(criterion: Pick<ResearchSkillCriterion, 'score_type'>) {
  const labels = {
    integer_scale: 'Integer scale',
    number: 'Number',
    single_choice: 'Single choice',
    boolean: 'Yes / No',
    text: 'Text',
  } satisfies Record<ResearchSkillCriterion['score_type'], string>
  return labels[criterion.score_type]
}

export function phaseSegmentLabel(segment: ResearchSkillPhaseSegment & { occurrence?: number }) {
  return `${segment.phase_name}${segment.occurrence ? ` #${segment.occurrence}` : ''}`
}
