import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'

test('research video notes dialog keeps a local draft and saves via notes endpoint', () => {
  const dialog = readFileSync(new URL('../src/components/research/ResearchVideoNotesDialog.vue', import.meta.url), 'utf8')
  const store = readFileSync(new URL('../src/stores/researchVideos.ts', import.meta.url), 'utf8')

  assert.match(dialog, /noteDraft/)
  assert.match(dialog, /noteChanged/)
  assert.match(dialog, /beforeClose/)
  assert.match(dialog, /maxlength="5000"/)
  assert.match(store, /updateVideoNotes/)
  assert.match(store, /\/api\/research\/videos\/\$\{videoId\}\/notes/)
})

test('research video list and checklist share the notes dialog component', () => {
  const videosPage = readFileSync(new URL('../src/views/ResearchVideosPage.vue', import.meta.url), 'utf8')
  const checklistPage = readFileSync(new URL('../src/views/ResearchVideoChecklistPage.vue', import.meta.url), 'utf8')

  assert.match(videosPage, /ResearchVideoNotesDialog/)
  assert.match(checklistPage, /ResearchVideoNotesDialog/)
  assert.match(videosPage, /researchVideos\.videoNotes/)
  assert.match(checklistPage, /researchVideos\.videoNotes/)
})
