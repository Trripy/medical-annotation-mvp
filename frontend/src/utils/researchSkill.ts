import type {
  ResearchSkillAssessmentDetail,
  ResearchSkillCriterion,
  ResearchSkillEvidence,
  ResearchSkillPhaseSegment,
  ResearchSkillScore,
} from '../types/researchSkill.ts'

export function sortSkillCriteria(criteria: readonly ResearchSkillCriterion[]) {
  return criteria.slice().sort((left, right) => left.display_order - right.display_order || left.id - right.id)
}

export function sortSkillEvidence(evidence: readonly ResearchSkillEvidence[]) {
  return evidence.slice().sort((left, right) => left.start_frame - right.start_frame || left.id - right.id)
}

export function isCriterionApplicableToTarget(
  criterion: Pick<ResearchSkillCriterion, 'scope' | 'phase_label_ids' | 'is_active'>,
  segment: Pick<ResearchSkillPhaseSegment, 'phase_label_id'> | null,
) {
  if (!criterion.is_active) {
    return false
  }
  if (criterion.scope === 'overall') {
    return segment === null
  }
  if (!segment) {
    return false
  }
  return criterion.phase_label_ids.length === 0 || criterion.phase_label_ids.includes(segment.phase_label_id)
}

export function getApplicableCriteria(
  assessment: ResearchSkillAssessmentDetail | null,
  targetType: 'overall' | 'phase',
  segment: ResearchSkillPhaseSegment | null,
) {
  if (!assessment) {
    return []
  }
  return sortSkillCriteria(assessment.rubric.criteria)
    .filter((criterion) => criterion.scope === (targetType === 'overall' ? 'overall' : 'phase'))
    .filter((criterion) => isCriterionApplicableToTarget(criterion, targetType === 'phase' ? segment : null))
}

export function getScoreTargetKey(targetType: 'overall' | 'phase_segment', phaseSegmentId: number | null) {
  return targetType === 'overall' ? 'overall' : phaseSegmentId === null ? '' : `segment:${phaseSegmentId}`
}

export function findSkillScore(
  scores: readonly ResearchSkillScore[],
  criterionId: number,
  targetType: 'overall' | 'phase_segment',
  phaseSegmentId: number | null,
) {
  const targetKey = getScoreTargetKey(targetType, phaseSegmentId)
  return scores.find((score) => score.criterion_id === criterionId && score.target_key === targetKey) ?? null
}

export function isSkillScoreComplete(score: ResearchSkillScore | null | undefined) {
  return Boolean(score && (score.is_na || score.value !== null && score.value !== undefined))
}

export function isSkillAssessmentReadOnly(status: string | null | undefined) {
  return status === 'submitted' || status === 'reviewed' || status === 'locked'
}

export function buildPhaseSegmentOccurrences(segments: readonly ResearchSkillPhaseSegment[]) {
  const counts = new Map<number, number>()
  return segments
    .slice()
    .sort((left, right) => left.start_frame - right.start_frame || left.id - right.id)
    .map((segment) => {
      const occurrence = (counts.get(segment.phase_label_id) ?? 0) + 1
      counts.set(segment.phase_label_id, occurrence)
      return {
        ...segment,
        occurrence,
        displayName: `${segment.phase_name} #${occurrence}`,
      }
    })
}

export function buildIntegerScaleOptions(minValue: number | null, maxValue: number | null, step: number | null) {
  if (minValue === null || maxValue === null || step === null || step <= 0 || maxValue < minValue) {
    return []
  }
  const options: number[] = []
  for (let value = minValue; value <= maxValue + 1e-9 && options.length < 100; value += step) {
    if (Number.isInteger(value)) {
      options.push(value)
    }
  }
  return options
}

export function normalizeScorePayloadValue(value: unknown, isNa: boolean) {
  return isNa ? null : value
}

export function canStoreScoreComment(score: ResearchSkillScore | null, nextValue: unknown, isNa: boolean) {
  return isSkillScoreComplete(score) || isNa || nextValue !== null && nextValue !== undefined && nextValue !== ''
}

export function evidenceToUiRange(evidence: Pick<ResearchSkillEvidence, 'start_frame' | 'end_frame_exclusive'>) {
  return {
    startFrame: evidence.start_frame + 1,
    endFrame: evidence.end_frame_exclusive === null ? null : evidence.end_frame_exclusive,
  }
}

export function uiRangeToEvidence(startFrame: number, inclusiveEndFrame: number | null) {
  return {
    start_frame: Math.max(0, startFrame - 1),
    end_frame_exclusive: inclusiveEndFrame,
  }
}

export function buildPointEvidence(currentFrameIndex: number) {
  return {
    start_frame: Math.max(0, currentFrameIndex),
    end_frame_exclusive: null,
  }
}

export function buildIntervalEvidence(startFrameIndex: number, finishFrameIndex: number) {
  const start = Math.min(startFrameIndex, finishFrameIndex)
  const end = Math.max(startFrameIndex, finishFrameIndex) + 1
  return {
    start_frame: Math.max(0, start),
    end_frame_exclusive: Math.max(start + 1, end),
  }
}

export function restoreSelectedCriterionId(
  previousCriterionId: number | null,
  criteria: readonly { id: number }[],
) {
  if (previousCriterionId !== null && criteria.some((criterion) => criterion.id === previousCriterionId)) {
    return previousCriterionId
  }
  return criteria[0]?.id ?? null
}

export function restoreSelectedScoreId(
  previousScoreId: number | null,
  scores: readonly { id: number }[],
) {
  if (previousScoreId !== null && scores.some((score) => score.id === previousScoreId)) {
    return previousScoreId
  }
  return null
}
