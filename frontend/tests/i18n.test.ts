import assert from 'node:assert/strict'
import test from 'node:test'

import { createI18n } from 'vue-i18n'

import { fallbackLocale, messages } from '../src/i18n/index.ts'
import enUS from '../src/i18n/locales/en-US.ts'
import zhCN from '../src/i18n/locales/zh-CN.ts'
import type { ResearchPhaseValidationIssue } from '../src/types/researchPhase.ts'
import type { ResearchSkillValidationIssue } from '../src/types/researchSkill.ts'
import {
  applyLocaleFromStorageEvent,
  formatDateTime,
  formatPercent,
  getPhaseLabelDisplayName,
  getPhaseProtocolDisplayName,
  LOCALE_STORAGE_KEY,
  persistLocale,
  replaceLocalePreservingQuery,
  resolveInitialLocale,
  translateApiErrorMessage,
  translatePhaseValidationIssue,
  translateSkillValidationIssue,
  translateStatus,
} from '../src/utils/locale.ts'

function flattenKeys(value: unknown, prefix = ''): string[] {
  if (!value || typeof value !== 'object') {
    return [prefix]
  }
  return Object.entries(value as Record<string, unknown>).flatMap(([key, child]) =>
    flattenKeys(child, prefix ? `${prefix}.${key}` : key),
  )
}

function makeT(locale: 'en-US' | 'zh-CN') {
  const i18n = createI18n({
    legacy: false,
    locale,
    fallbackLocale: 'en-US',
    messages,
    missingWarn: false,
    fallbackWarn: false,
  })
  return i18n.global.t
}

test('locale initializes from legal localStorage values', () => {
  assert.equal(resolveInitialLocale('zh-CN', 'en-US'), 'zh-CN')
  assert.equal(resolveInitialLocale('en-US', 'zh-CN'), 'en-US')
})

test('locale falls back safely for illegal localStorage values', () => {
  assert.equal(resolveInitialLocale('fr-FR', 'en-US'), 'en-US')
  assert.equal(resolveInitialLocale(null, 'zh-Hans-CN'), 'zh-CN')
  assert.equal(resolveInitialLocale(undefined, 'en-US'), 'en-US')
})

test('message key sets are identical and fallback locale is English', () => {
  assert.deepEqual(flattenKeys(zhCN).sort(), flattenKeys(enUS).sort())
  assert.equal(fallbackLocale, 'en-US')
})

test('persistLocale writes localStorage and document lang', () => {
  const writes: Record<string, string> = {}
  const previousDocument = globalThis.document
  Object.defineProperty(globalThis, 'document', {
    configurable: true,
    value: { documentElement: { lang: '' } },
  })

  persistLocale('zh-CN', { setItem: (key, value) => { writes[key] = value } })

  assert.equal(writes[LOCALE_STORAGE_KEY], 'zh-CN')
  assert.equal(document.documentElement.lang, 'zh-CN')

  Object.defineProperty(globalThis, 'document', {
    configurable: true,
    value: previousDocument,
  })
})

test('storage event applies locale across tabs', () => {
  let applied = ''
  assert.equal(applyLocaleFromStorageEvent({ key: LOCALE_STORAGE_KEY, newValue: 'en-US' }, (locale) => { applied = locale }), true)
  assert.equal(applied, 'en-US')
  assert.equal(applyLocaleFromStorageEvent({ key: LOCALE_STORAGE_KEY, newValue: 'bad' }, () => { applied = 'bad' }), false)
  assert.equal(applied, 'en-US')
})

test('built-in phase protocol and labels localize without changing custom data', () => {
  assert.equal(getPhaseProtocolDisplayName({ name: 'Cataract Surgery Phases', is_default: true }, 'zh-CN'), '白内障手术阶段')
  assert.equal(getPhaseProtocolDisplayName({ name: 'My Protocol', is_default: false }, 'zh-CN'), 'My Protocol')
  assert.equal(getPhaseLabelDisplayName({ key: 'incision', name: 'Incision' }, 'zh-CN'), '切口制作')
  assert.equal(getPhaseLabelDisplayName({ key: 'custom', name: 'Custom Label' }, 'zh-CN'), 'Custom Label')
})

test('status labels are localized by display layer only', () => {
  assert.equal(translateStatus('draft', makeT('zh-CN')), '草稿')
  assert.equal(translateStatus('submitted', makeT('en-US')), 'Submitted')
})

test('phase and skill validation issue localization uses issue_type with fallback', () => {
  const phaseIssue = {
    issue_type: 'no_segments',
    severity: 'error',
    message: 'No segments from backend',
    segment_id: null,
    related_segment_id: null,
    frame_start: null,
    frame_end_exclusive: null,
    details: {},
  } satisfies ResearchPhaseValidationIssue
  assert.equal(translatePhaseValidationIssue(phaseIssue, makeT('zh-CN')), '尚未创建阶段区间。')

  const skillIssue = {
    issue_type: 'missing_required_score',
    severity: 'error',
    message: 'Backend skill message',
    criterion_id: 1,
    score_id: null,
    phase_segment_id: null,
    evidence_id: null,
    details: {},
  } satisfies ResearchSkillValidationIssue
  assert.equal(translateSkillValidationIssue(skillIssue, makeT('zh-CN')), '缺少必填评分。')

  const unknownIssue = { ...skillIssue, issue_type: 'future_issue' as ResearchSkillValidationIssue['issue_type'], message: 'Future backend message' }
  assert.equal(translateSkillValidationIssue(unknownIssue, makeT('zh-CN')), 'Future backend message')
})

test('API error localization maps known messages and preserves unknown messages', () => {
  assert.equal(translateApiErrorMessage('Skill assessment revision conflict.', makeT('zh-CN')), '技能评估版本冲突。')
  assert.equal(translateApiErrorMessage('Unknown backend error.', makeT('zh-CN')), 'Unknown backend error.')
})

test('boolean false and API enum payloads are not translated by helpers', () => {
  const payload = { value: false, status: 'draft', target_type: 'phase_segment' }
  assert.equal(payload.value, false)
  assert.equal(payload.status, 'draft')
  assert.equal(payload.target_type, 'phase_segment')
})

test('formatters follow locale and handle invalid dates', () => {
  assert.equal(formatPercent(50, 'en-US'), '50%')
  assert.equal(formatPercent(50, 'zh-CN'), '50%')
  assert.equal(formatDateTime('not-a-date', 'zh-CN'), '--')
})

test('locale helper preserves current route and query state', () => {
  const route = { path: '/research/videos/2/skills', query: { frame: '24', assessment: '9' } }
  const next = replaceLocalePreservingQuery(route)
  assert.equal(next, route)
  assert.deepEqual(next.query, { frame: '24', assessment: '9' })
})
