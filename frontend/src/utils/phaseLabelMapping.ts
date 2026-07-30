import type {
  ResearchPhaseLabelMappingProfileDetail,
  ResearchPhaseSegment,
} from '../types/researchPhase'

export type PhaseLabelViewMode = 'original' | 'mapped'

export type MappedResearchPhaseSegment = Omit<ResearchPhaseSegment, 'end_frame_exclusive' | 'phase_label'> & {
  end_frame_exclusive: number
  phase_label: ResearchPhaseSegment['phase_label']
  mapped_target_key: string
  mapped_target_name: string
  mapped_target_color: string
  source_segment_ids: number[]
  source_label_ids: number[]
  source_label_names: string[]
}

const VIDEO_EXTENSIONS = ['.mp4', '.mov', '.m4v', '.avi', '.mkv', '.webm']
const WINDOWS_RESERVED = new Set(['CON', 'PRN', 'AUX', 'NUL', ...Array.from({ length: 9 }, (_, index) => `COM${index + 1}`), ...Array.from({ length: 9 }, (_, index) => `LPT${index + 1}`)])

export function mapAndMergePhaseSegments(
  segments: readonly ResearchPhaseSegment[],
  profile: ResearchPhaseLabelMappingProfileDetail | null,
  frameCount: number,
): MappedResearchPhaseSegment[] {
  if (!profile) {
    return []
  }
  const ruleBySourceLabelId = new Map<number, {
    target: ResearchPhaseLabelMappingProfileDetail['targets'][number]
    sourceLabel: ResearchPhaseLabelMappingProfileDetail['targets'][number]['source_labels'][number]
  }>()
  for (const target of profile.targets) {
    for (const sourceLabel of target.source_labels) {
      ruleBySourceLabelId.set(sourceLabel.id, { target, sourceLabel })
    }
  }

  const mapped: MappedResearchPhaseSegment[] = []
  for (const segment of segments.slice().sort((left, right) => left.start_frame - right.start_frame || left.id - right.id)) {
    const rule = ruleBySourceLabelId.get(segment.phase_label_id)
    if (!rule) {
      continue
    }
    const endFrameExclusive = segment.end_frame_exclusive ?? frameCount
    mapped.push({
      ...segment,
      end_frame_exclusive: endFrameExclusive,
      phase_label: {
        id: rule.target.id,
        key: rule.target.key,
        name: rule.target.name,
        color: rule.target.color,
      },
      mapped_target_key: rule.target.key,
      mapped_target_name: rule.target.name,
      mapped_target_color: rule.target.color,
      source_segment_ids: [segment.id],
      source_label_ids: [segment.phase_label_id],
      source_label_names: [segment.phase_label.name],
    })
  }

  const merged: MappedResearchPhaseSegment[] = []
  for (const segment of mapped) {
    const previous = merged[merged.length - 1]
    if (previous && previous.mapped_target_key === segment.mapped_target_key && previous.end_frame_exclusive === segment.start_frame) {
      previous.end_frame_exclusive = segment.end_frame_exclusive
      previous.source_segment_ids = previous.source_segment_ids.concat(segment.source_segment_ids)
      previous.source_label_ids = uniqueNumbers(previous.source_label_ids.concat(segment.source_label_ids))
      previous.source_label_names = uniqueStrings(previous.source_label_names.concat(segment.source_label_names))
      continue
    }
    merged.push({ ...segment })
  }
  return merged
}

export function calculateMappedFrameConservation(
  sourceSegments: readonly ResearchPhaseSegment[],
  mappedSegments: readonly MappedResearchPhaseSegment[],
  frameCount: number,
) {
  const sourceFrames = sourceSegments.reduce((total, segment) => total + Math.max(0, (segment.end_frame_exclusive ?? frameCount) - segment.start_frame), 0)
  const mappedFrames = mappedSegments.reduce((total, segment) => total + Math.max(0, (segment.end_frame_exclusive ?? frameCount) - segment.start_frame), 0)
  return {
    sourceFrames,
    mappedFrames,
    passed: sourceFrames === mappedFrames,
  }
}

export function slugifyMappingKey(name: string) {
  return name
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_.-]+/g, '-')
    .replace(/-+/g, '-')
    .replace(/^[-_.]+|[-_.]+$/g, '')
    .slice(0, 80)
}

export function buildPhaseExportFilename(options: {
  videoDisplayName: string | null | undefined
  videoId: number
  mappingProfileKey?: string | null
  mappingMode: 'original' | 'profile'
}) {
  const stem = safePhaseFilenameStem(stripVideoExtension((options.videoDisplayName ?? '').trim())) || `research-video-${options.videoId}`
  if (options.mappingMode === 'profile' && options.mappingProfileKey) {
    return `${stem}__${safePhaseFilenameStem(options.mappingProfileKey) || 'mapping-profile'}.json`
  }
  return `${stem}.json`
}

function stripVideoExtension(name: string) {
  const lowerName = name.toLowerCase()
  const extension = VIDEO_EXTENSIONS.find((candidate) => lowerName.endsWith(candidate))
  return extension ? name.slice(0, -extension.length) : name
}

function safePhaseFilenameStem(value: string) {
  const sanitized = value
    .replace(/[\x00-\x1f\x7f]/g, '')
    .replace(/[\\/:*?"<>|]/g, '_')
    .replace(/\s+/g, ' ')
    .replace(/[. ]+$/g, '')
    .trim()
    .slice(0, 180)
    .replace(/[. ]+$/g, '')
  if (!sanitized) {
    return ''
  }
  return WINDOWS_RESERVED.has(sanitized.toUpperCase()) ? `${sanitized}_file` : sanitized
}

function uniqueNumbers(values: number[]) {
  return Array.from(new Set(values))
}

function uniqueStrings(values: string[]) {
  return Array.from(new Set(values))
}
