import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'

test('research video list requests visible videos by default and exposes visibility filter', () => {
  const store = readFileSync(new URL('../src/stores/researchVideos.ts', import.meta.url), 'utf8')
  const page = readFileSync(new URL('../src/views/ResearchVideosPage.vue', import.meta.url), 'utf8')

  assert.match(store, /visibility:\s*'visible'/)
  assert.match(store, /URLSearchParams\(\{\s*visibility:\s*requestedVisibility\s*\}\)/)
  assert.match(page, /visibilityFilter/)
  assert.match(page, /researchVideos\.allVisibility/)
  assert.match(page, /restoreVideo/)
})

test('checklist manages hidden videos without removing checklist access', () => {
  const page = readFileSync(new URL('../src/views/ResearchVideoChecklistPage.vue', import.meta.url), 'utf8')

  assert.match(page, /hide-trimmed-sources\/preview/)
  assert.match(page, /restore-trimmed-sources\/preview/)
  assert.match(page, /filters\.visibility/)
  assert.match(page, /restoreSingleVideo/)
  assert.match(page, /hidden_from_video_list/)
  assert.match(page, /videoChecklist\.visibilityStatus/)
})
