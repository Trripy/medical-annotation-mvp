import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const focusedFiles = [
  'src/views/AnnotatePage.vue',
  'src/views/JobsPage.vue',
  'src/views/AnnotationWorkbench.vue',
  'src/views/AnnotationLandingPage.vue',
  'src/views/DatasetsPage.vue',
  'src/components/AnnotationCanvas.vue',
]

const allowedTemplateText = new Set([
  'SAM2',
  'N/A',
])

const allowedStringFragments = [
  'LabelMe',
  'COCO',
  'CVAT',
  'YOLO',
  'VIA',
  'Supervisely',
  'Pascal VOC',
  'Mask PNG',
  'JSON',
  'XML',
  'TXT',
  'ZIP',
  'API',
  'ID:',
  'Job #',
  'Project #',
  'case001',
  'layer_down',
  'Pig Eye OCT',
  'sam2_hiera_',
  'object_annotation',
  'image_classification',
  'classification',
  'polygon',
  'rectangle',
  'point',
  'tracked',
  'pending',
  'accepted',
  'rejected',
  'needs_fix',
  'failed',
]

function source(file: string): string {
  return readFileSync(new URL(`../${file}`, import.meta.url), 'utf8')
}

function isAllowedString(value: string): boolean {
  return allowedStringFragments.some((fragment) => value.includes(fragment))
}

test('focused frontend files do not contain plain hardcoded English template text', () => {
  const offenders: string[] = []
  const pattern = />\s*([A-Z][A-Za-z0-9 ,:/()_.+-]{2,})\s*</g

  for (const file of focusedFiles) {
    const text = source(file)
    for (const match of text.matchAll(pattern)) {
      const value = match[1].trim()
      if (!allowedTemplateText.has(value) && !isAllowedString(value)) {
        offenders.push(`${file}: ${value}`)
      }
    }
  }

  assert.deepEqual(offenders, [])
})

test('focused frontend files do not hardcode English toast or confirm text', () => {
  const offenders: string[] = []
  const pattern = /(ElMessage\.(?:success|warning|error|info)\(|ElMessageBox\.confirm\(|window\.confirm\()\s*(['"`])([A-Z][^'"`]*?)\2/g

  for (const file of focusedFiles) {
    const text = source(file)
    for (const match of text.matchAll(pattern)) {
      const value = match[3].trim()
      if (!isAllowedString(value)) {
        offenders.push(`${file}: ${value}`)
      }
    }
  }

  assert.deepEqual(offenders, [])
})

test('focused frontend files localize placeholder title and aria-label text', () => {
  const offenders: string[] = []
  const pattern = /\s(?:placeholder|title|aria-label)="([A-Z][^"]+)"/g

  for (const file of focusedFiles) {
    const text = source(file)
    for (const match of text.matchAll(pattern)) {
      const value = match[1].trim()
      if (!isAllowedString(value)) {
        offenders.push(`${file}: ${value}`)
      }
    }
  }

  assert.deepEqual(offenders, [])
})

test('technical terms remain displayable without changing API enum payloads', () => {
  const jobs = source('src/views/JobsPage.vue')
  const annotate = source('src/views/AnnotatePage.vue')

  assert.match(jobs, /LabelMe JSON/)
  assert.match(jobs, /COCO JSON/)
  assert.match(jobs, /YOLO TXT \/ ZIP/)
  assert.match(annotate, /value="polygon"/)
  assert.match(annotate, /value="rectangle"/)
  assert.match(annotate, /value="point"/)
  assert.match(annotate, /value="object_annotation"/)
  assert.match(annotate, /value="image_classification"/)
})
