import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'

const styles = readFileSync(new URL('../src/styles.css', import.meta.url), 'utf8')
const videosPage = readFileSync(new URL('../src/views/ResearchVideosPage.vue', import.meta.url), 'utf8')

function cssBlock(selector: string) {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const match = styles.match(new RegExp(`${escaped}\\s*\\{(?<body>[^}]*)\\}`, 's'))
  assert.ok(match?.groups?.body, `Missing CSS block for ${selector}`)
  return match.groups.body
}

test('research video cards use semantic layout areas instead of positional selectors', () => {
  assert.match(videosPage, /class="research-video-thumb"/)
  assert.match(videosPage, /class="research-video-meta"/)
  assert.match(videosPage, /class="research-video-phase-summary"/)
  assert.match(videosPage, /class="research-video-notes-summary"/)
  assert.match(videosPage, /class="research-video-actions"/)

  const cardStyles = styles.slice(styles.indexOf('.research-video-grid'), styles.indexOf('.research-empty-state'))
  assert.doesNotMatch(cardStyles, /nth-child/)
  assert.doesNotMatch(cardStyles, /margin-left:\s*-/)
  assert.doesNotMatch(cardStyles, /position:\s*absolute/)
})

test('research video card thumbnail dimensions are controlled by the grid cell', () => {
  const grid = cssBlock('.research-video-grid')
  const thumb = cssBlock('.research-video-thumb')
  const img = styles.match(/\.research-video-thumb img,\s*\n\.research-video-player\s*\{(?<body>[^}]*)\}/s)?.groups?.body ?? ''

  assert.match(grid, /container-type:\s*inline-size/)
  assert.match(thumb, /grid-area:\s*thumbnail/)
  assert.match(thumb, /width:\s*100%/)
  assert.match(thumb, /min-width:\s*0/)
  assert.match(thumb, /aspect-ratio:\s*16\s*\/\s*9/)
  assert.match(img, /display:\s*block/)
  assert.match(img, /width:\s*100%/)
  assert.doesNotMatch(img, /width:\s*(?:2[1-9]\d|[3-9]\d\d)px/)
})

test('research video card has responsive wide, medium, and narrow grid layouts', () => {
  const card = cssBlock('.research-video-card')

  assert.match(card, /grid-template-columns:\s*[\s\S]*minmax\(190px,\s*230px\)[\s\S]*max-content/)
  assert.match(card, /grid-template-areas:\s*"thumbnail info phase notes actions"/)
  assert.match(card, /height:\s*auto/)
  assert.doesNotMatch(card, /height:\s*\d+px/)

  assert.match(styles, /@container\s*\(max-width:\s*1279px\)\s*\{[\s\S]*"thumbnail info actions"[\s\S]*"thumbnail phase phase"[\s\S]*"thumbnail notes notes"/)
  assert.match(styles, /@container\s*\(max-width:\s*879px\)\s*\{[\s\S]*grid-template-columns:\s*minmax\(0,\s*1fr\)[\s\S]*"thumbnail"[\s\S]*"info"[\s\S]*"phase"[\s\S]*"notes"[\s\S]*"actions"/)
})

test('research video card text regions can shrink and wrap without overlapping thumbnails', () => {
  const meta = cssBlock('.research-video-meta')
  const title = cssBlock('.research-video-title-row h3')
  const phase = cssBlock('.research-video-phase-summary,\n.research-video-notes-summary')
  const notes = cssBlock('.research-video-notes-text')
  const actions = cssBlock('.research-video-actions')
  const stats = cssBlock('.research-video-stats,\n.research-video-created')

  assert.match(meta, /grid-area:\s*info/)
  assert.match(meta, /min-width:\s*0/)
  assert.match(title, /-webkit-line-clamp:\s*2/)
  assert.match(title, /overflow-wrap:\s*anywhere/)
  assert.match(phase, /min-width:\s*0/)
  assert.match(phase, /width:\s*100%/)
  assert.match(notes, /-webkit-line-clamp:\s*2/)
  assert.match(notes, /word-break:\s*break-word/)
  assert.match(actions, /grid-area:\s*actions/)
  assert.match(actions, /flex-wrap:\s*wrap/)
  assert.match(stats, /flex-wrap:\s*wrap/)
})

test('research videos page topbar and content avoid page-level horizontal overflow', () => {
  assert.match(cssBlock('.content'), /min-width:\s*0/)
  assert.match(cssBlock('.content'), /overflow-x:\s*hidden/)
  assert.match(cssBlock('.topbar'), /flex-wrap:\s*wrap/)
  assert.match(cssBlock('.topbar-actions'), /flex-wrap:\s*wrap/)
  assert.match(cssBlock('.research-video-visibility-select'), /width:\s*clamp\(120px,\s*16vw,\s*160px\)/)

  const videoStyles = styles.slice(styles.indexOf('.research-video-grid'), styles.indexOf('.research-trim-page'))
  assert.doesNotMatch(videoStyles, /100vw/)
})
