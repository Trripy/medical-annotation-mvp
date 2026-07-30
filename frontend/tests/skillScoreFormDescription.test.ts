import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const source = readFileSync(new URL('../src/components/research/SkillScoreForm.vue', import.meta.url), 'utf8')

test('SkillScoreForm preserves long criterion description line breaks without v-html', () => {
  assert.match(source, /skill-criterion-description/)
  assert.match(source, /white-space:\s*pre-line/)
  assert.match(source, /overflow-wrap:\s*anywhere/)
  assert.doesNotMatch(source, /v-html/)
})

test('SkillScoreForm renders single choice scoring as compact score cards', () => {
  assert.match(source, /skill-choice-card-list/)
  assert.match(source, /role="radiogroup"/)
  assert.match(source, /skill-choice-card-score/)
  assert.match(source, /aria-checked/)
})
