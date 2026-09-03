import type { ComposerTranslation } from 'vue-i18n'

import type { ResearchPhaseLabel, ResearchPhaseProtocolSummary, ResearchPhaseValidationIssue } from '../types/researchPhase'
import type { ResearchSkillValidationIssue } from '../types/researchSkill'

export const SUPPORTED_LOCALES = ['zh-CN', 'en-US'] as const
export type SupportedLocale = typeof SUPPORTED_LOCALES[number]
export const DEFAULT_LOCALE: SupportedLocale = 'en-US'
export const LOCALE_STORAGE_KEY = 'medical-annotation-locale'

export function isSupportedLocale(value: unknown): value is SupportedLocale {
  return typeof value === 'string' && (SUPPORTED_LOCALES as readonly string[]).includes(value)
}

export function resolveInitialLocale(storageValue: unknown, navigatorLanguage: unknown): SupportedLocale {
  if (isSupportedLocale(storageValue)) {
    return storageValue
  }
  if (typeof navigatorLanguage === 'string' && navigatorLanguage.toLowerCase().startsWith('zh')) {
    return 'zh-CN'
  }
  return DEFAULT_LOCALE
}

export function readPersistedLocale(storage: Pick<Storage, 'getItem'> | null | undefined, navigatorLanguage: string | undefined): SupportedLocale {
  let storageValue: string | null = null
  try {
    storageValue = storage?.getItem(LOCALE_STORAGE_KEY) ?? null
  } catch {
    storageValue = null
  }
  return resolveInitialLocale(storageValue, navigatorLanguage)
}

export function persistLocale(locale: SupportedLocale, storage: Pick<Storage, 'setItem'> | null | undefined = globalThis.localStorage): void {
  try {
    storage?.setItem(LOCALE_STORAGE_KEY, locale)
  } catch {
    // Locale persistence must never block the application.
  }
  if (typeof document !== 'undefined') {
    document.documentElement.lang = locale
  }
}

export function applyLocaleFromStorageEvent(
  event: Pick<StorageEvent, 'key' | 'newValue'>,
  apply: (locale: SupportedLocale) => void,
): boolean {
  if (event.key !== LOCALE_STORAGE_KEY || !isSupportedLocale(event.newValue)) {
    return false
  }
  apply(event.newValue)
  return true
}

const BUILTIN_PHASE_PROTOCOL_NAMES: Record<SupportedLocale, Record<string, string>> = {
  'en-US': {
    'Cataract Surgery Phases': 'Cataract Surgery Phases',
  },
  'zh-CN': {
    'Cataract Surgery Phases': '白内障手术阶段',
  },
}

const BUILTIN_PHASE_LABEL_NAMES: Record<SupportedLocale, Record<string, string>> = {
  'en-US': {
    idle: 'Idle',
    incision: 'Incision',
    viscoelastic: 'Viscoelastic Injection',
    capsulorhexis: 'Capsulorhexis',
    hydrodissection: 'Hydrodissection',
    phacoemulsification: 'Phacoemulsification',
    irrigation_aspiration: 'Irrigation / Aspiration',
    capsule_polishing: 'Capsule Polishing',
    lens_implantation: 'Lens Implantation',
    lens_positioning: 'Lens Positioning',
    viscoelastic_suction: 'Viscoelastic Suction',
    anterior_chamber_flushing: 'Anterior Chamber Flushing',
    tonifying_antibiotics: 'Tonifying / Antibiotics',
  },
  'zh-CN': {
    idle: '空闲阶段',
    incision: '切口制作',
    viscoelastic: '黏弹剂注入',
    capsulorhexis: '连续环形撕囊',
    hydrodissection: '水分离',
    phacoemulsification: '超声乳化',
    irrigation_aspiration: '灌注与抽吸',
    capsule_polishing: '囊膜抛光',
    lens_implantation: '人工晶状体植入',
    lens_positioning: '人工晶状体调整',
    viscoelastic_suction: '黏弹剂吸除',
    anterior_chamber_flushing: '前房冲洗',
    tonifying_antibiotics: '切口处理与抗生素',
  },
}

export function getPhaseProtocolDisplayName(
  protocol: Pick<ResearchPhaseProtocolSummary, 'name' | 'is_default'> | null | undefined,
  locale: SupportedLocale,
): string {
  if (!protocol) {
    return ''
  }
  if (!protocol.is_default) {
    return protocol.name
  }
  return BUILTIN_PHASE_PROTOCOL_NAMES[locale][protocol.name] ?? protocol.name
}

export function getPhaseLabelDisplayName(
  label: Pick<ResearchPhaseLabel, 'key' | 'name'> | { phase_key?: string; phase_name?: string; key?: string; name?: string } | null | undefined,
  locale: SupportedLocale,
): string {
  if (!label) {
    return ''
  }
  const key = 'key' in label ? label.key : label.phase_key
  const name = 'name' in label ? label.name : label.phase_name
  if (key && BUILTIN_PHASE_LABEL_NAMES[locale][key]) {
    return BUILTIN_PHASE_LABEL_NAMES[locale][key]
  }
  return name ?? ''
}

export function translateStatus(value: string | null | undefined, t: ComposerTranslation): string {
  if (!value) {
    return t('common.placeholder')
  }
  const translated = t(`status.${value}`)
  return translated === `status.${value}` ? value : translated
}

function issueRange(details: Record<string, unknown> | undefined, start?: number | null, end?: number | null): string {
  const detailStart = typeof details?.frame_start === 'number' ? details.frame_start : start
  const detailEnd = typeof details?.frame_end_exclusive === 'number' ? details.frame_end_exclusive : end
  if (typeof detailStart === 'number' && typeof detailEnd === 'number') {
    return `${detailStart + 1}-${detailEnd}`
  }
  if (typeof detailStart === 'number') {
    return String(detailStart + 1)
  }
  return ''
}

export function translatePhaseValidationIssue(issue: ResearchPhaseValidationIssue, t: ComposerTranslation): string {
  const key = `validation.phase.${issue.issue_type}`
  const translated = t(key, {
    range: issueRange(issue.details, issue.frame_start, issue.frame_end_exclusive),
  })
  return translated === key ? issue.message : translated
}

export function translateSkillValidationIssue(issue: ResearchSkillValidationIssue, t: ComposerTranslation): string {
  const key = `validation.skill.${issue.issue_type}`
  const translated = t(key, {
    criterion: typeof issue.details?.criterion === 'string' ? issue.details.criterion : '',
    phase: typeof issue.details?.phase === 'string' ? issue.details.phase : '',
  })
  return translated === key ? issue.message : translated
}

const API_ERROR_KEYS: Record<string, string> = {
  'Phase annotation set revision conflict.': 'errors.phaseConflict',
  'Skill assessment revision conflict.': 'errors.skillConflict',
  'Only draft phase annotation sets can be modified.': 'errors.phaseReadOnly',
  'Phase segment overlaps an existing segment.': 'phaseAnnotation.segmentOverlap',
  'Only draft skill assessments can be modified.': 'errors.skillReadOnly',
  'Phase annotation set has validation errors.': 'errors.phaseValidationErrors',
  'Phase annotation set has warnings that require confirmation.': 'errors.phaseWarningsConfirm',
  'Skill assessment has validation errors.': 'errors.skillValidationErrors',
  'Skill assessment has warnings that require confirmation.': 'errors.skillWarningsConfirm',
  'No active phase segment was found.': 'errors.noActivePhaseSegment',
  'No active phase protocol is available.': 'errors.noActivePhaseProtocol',
  'Research video not found.': 'errors.videoNotFound',
  'User not found.': 'errors.userNotFound',
  'Skill rubric not found.': 'errors.rubricNotFound',
  'Skill assessment not found.': 'errors.assessmentNotFound',
  'Invalid score value.': 'errors.invalidScoreValue',
  'This criterion does not allow N/A.': 'errors.naNotAllowed',
  'Evidence frame is outside the video range.': 'errors.evidenceOutOfBounds',
}

export function translateApiErrorMessage(message: string | null | undefined, t: ComposerTranslation): string {
  if (!message) {
    return ''
  }
  const key = API_ERROR_KEYS[message]
  return key ? t(key) : message
}

export function formatDateTime(value: string | Date | null | undefined, locale: SupportedLocale): string {
  if (!value) {
    return '--'
  }
  const date = value instanceof Date ? value : new Date(value)
  if (Number.isNaN(date.getTime())) {
    return '--'
  }
  return new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' }).format(date)
}

export function formatDate(value: string | Date | null | undefined, locale: SupportedLocale): string {
  if (!value) {
    return '--'
  }
  const date = value instanceof Date ? value : new Date(value)
  if (Number.isNaN(date.getTime())) {
    return '--'
  }
  return new Intl.DateTimeFormat(locale, { dateStyle: 'medium' }).format(date)
}

export function formatTime(value: string | Date | null | undefined, locale: SupportedLocale): string {
  if (!value) {
    return '--'
  }
  const date = value instanceof Date ? value : new Date(value)
  if (Number.isNaN(date.getTime())) {
    return '--'
  }
  return new Intl.DateTimeFormat(locale, { timeStyle: 'medium' }).format(date)
}

export function formatNumber(value: number | null | undefined, locale: SupportedLocale): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return '--'
  }
  return new Intl.NumberFormat(locale, { maximumFractionDigits: 2 }).format(value)
}

export function formatPercent(value: number | null | undefined, locale: SupportedLocale): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return '--'
  }
  return new Intl.NumberFormat(locale, { maximumFractionDigits: 2, style: 'percent' }).format(value / 100)
}

export function formatDuration(valueMs: number | null | undefined): string {
  if (valueMs === null || valueMs === undefined || valueMs < 0 || !Number.isFinite(valueMs)) {
    return '--'
  }
  const totalSeconds = Math.floor(valueMs / 1000)
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
}

export function replaceLocalePreservingQuery<T extends { query?: unknown }>(routeLike: T): T {
  return routeLike
}
