import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'

import { parseContentDispositionFilename, downloadBlobWithFilename } from '../src/utils/download.ts'
import { buildPhaseExportFilename } from '../src/utils/phaseLabelMapping.ts'

test('phase export filename preview and download fallback use the same computed name', () => {
  const preview = buildPhaseExportFilename({
    videoDisplayName: '前后联合 张燕平 男 76_cleaned_trimmed.mp4',
    videoId: 54,
    mappingMode: 'original',
  })
  const actualDownloadName = parseContentDispositionFilename(null) ?? preview ?? 'research-video-54.json'

  assert.equal(preview, '前后联合 张燕平 男 76_cleaned_trimmed.json')
  assert.equal(actualDownloadName, preview)
  assert.notEqual(actualDownloadName, 'research-video-54.json')
})

test('phase export filename handles video extensions and mapped profile suffixes', () => {
  assert.equal(
    buildPhaseExportFilename({ videoDisplayName: 'CASE001.MP4', videoId: 54, mappingMode: 'original' }),
    'CASE001.json',
  )
  assert.equal(
    buildPhaseExportFilename({ videoDisplayName: 'case001', videoId: 54, mappingMode: 'original' }),
    'case001.json',
  )
  assert.equal(
    buildPhaseExportFilename({
      videoDisplayName: '前后联合 张燕平 男 76_cleaned_trimmed.mp4',
      videoId: 54,
      mappingMode: 'profile',
      mappingProfileKey: 'cataract-lmm-merged',
    }),
    '前后联合 张燕平 男 76_cleaned_trimmed__cataract-lmm-merged.json',
  )
})

test('content disposition parser prefers filename star and supports safe fallbacks', () => {
  assert.equal(
    parseContentDispositionFilename('attachment; filename="phase-export.json"; filename*=UTF-8\'\'%E5%89%8D%E5%90%8E%E8%81%94%E5%90%88.json'),
    '前后联合.json',
  )
  assert.equal(parseContentDispositionFilename("attachment; filename='plain.json'"), 'plain.json')
  assert.equal(parseContentDispositionFilename('attachment; filename=plain.json'), 'plain.json')
  assert.equal(parseContentDispositionFilename(null), null)
})

test('download helper clicks once and revokes object URLs after the click task', async () => {
  const clickedDownloads: string[] = []
  const revokedUrls: string[] = []
  const documentLike = {
    body: {
      appendChild() {},
    },
    createElement() {
      return {
        href: '',
        download: '',
        click() {
          clickedDownloads.push(this.download)
        },
        remove() {},
      }
    },
  } as unknown as Document
  const urlLike = {
    createObjectURL() {
      return 'blob:phase-export'
    },
    revokeObjectURL(url: string) {
      revokedUrls.push(url)
    },
  }

  downloadBlobWithFilename({
    blob: new Blob(['{}'], { type: 'application/json' }),
    filename: '前后联合 张燕平 男 76_cleaned_trimmed.json',
    documentLike,
    urlLike,
  })

  assert.deepEqual(clickedDownloads, ['前后联合 张燕平 男 76_cleaned_trimmed.json'])
  assert.deepEqual(revokedUrls, [])
  await new Promise((resolve) => setTimeout(resolve, 0))
  assert.deepEqual(revokedUrls, ['blob:phase-export'])
})

test('phase mapping drawer defaults to a simple merge workflow', () => {
  const source = readFileSync(new URL('../src/views/ResearchVideoPhasePage.vue', import.meta.url), 'utf8')

  assert.match(source, /phaseMapping\.simpleMode/)
  assert.match(source, /phaseMapping\.selectClasses/)
  assert.match(source, /phaseMapping\.mergedClassName/)
  assert.match(source, /phaseMapping\.currentMergedGroups/)
  assert.match(source, /phaseMapping\.viewAllMappings/)
  assert.match(source, /phase-mapping-table/)
  assert.doesNotMatch(source, /class="phase-mapping-target-list"/)
})

test('phase sidebar cards use document flow and label list owns remaining scroll space', () => {
  const source = readFileSync(new URL('../src/views/ResearchVideoPhasePage.vue', import.meta.url), 'utf8')

  assert.match(source, /\.research-phase-sidebar\s*\{[^}]*overflow-y:\s*auto/s)
  assert.match(source, /\.research-phase-sidebar \.research-phase-card\s*\{[^}]*height:\s*auto/s)
  assert.match(source, /\.research-phase-sidebar \.research-phase-card:nth-child\(4\)\s*\{[^}]*flex:\s*1 1 auto/s)
  assert.doesNotMatch(source, /\.research-phase-sidebar \.research-phase-card:nth-child\(3\)\s*\{[^}]*flex:\s*1 1 auto/s)
  assert.match(source, /\.research-phase-label-list\s*\{[^}]*overflow:\s*auto/s)
})
