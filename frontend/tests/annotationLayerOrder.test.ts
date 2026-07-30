import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import type { AnnotationObject } from '../src/stores/annotation.ts'
import {
  moveAnnotationLayer,
  moveAnnotationLayerByStep,
  moveAnnotationToBack,
  moveAnnotationToFront,
  nextTopLayerOrder,
  normalizeAnnotationLayerOrder,
  sortAnnotationsBackToFront,
  sortAnnotationsFrontToBack,
} from '../src/utils/annotationLayerOrder.ts'

function annotation(id: number, zOrder: number): AnnotationObject {
  return {
    id,
    image_id: 1,
    label_id: id,
    shape_type: 'rectangle',
    points: [[0, 0], [10, 10]],
    attributes: null,
    z_order: zOrder,
  }
}

test('ObjectPanel displays annotations from foreground to background', () => {
  const ordered = sortAnnotationsFrontToBack([annotation(1, 0), annotation(2, 2), annotation(3, 1)])
  assert.deepEqual(ordered.map((item) => item.id), [2, 3, 1])
})

test('Canvas draw order is background to foreground', () => {
  const ordered = sortAnnotationsBackToFront([annotation(1, 0), annotation(2, 2), annotation(3, 1)])
  assert.deepEqual(ordered.map((item) => item.id), [1, 3, 2])
})

test('moving an annotation up raises it one visible layer', () => {
  const moved = moveAnnotationLayerByStep([annotation(1, 0), annotation(2, 1), annotation(3, 2)], 2, -1)
  assert.deepEqual(sortAnnotationsFrontToBack(moved).map((item) => item.id), [2, 3, 1])
})

test('moving an annotation down lowers it one visible layer', () => {
  const moved = moveAnnotationLayerByStep([annotation(1, 0), annotation(2, 1), annotation(3, 2)], 2, 1)
  assert.deepEqual(sortAnnotationsFrontToBack(moved).map((item) => item.id), [3, 1, 2])
})

test('moving to top and bottom preserves ids and normalizes layer order', () => {
  const top = moveAnnotationToFront([annotation(1, 4), annotation(2, 9), annotation(3, 12)], 1)
  assert.deepEqual(sortAnnotationsFrontToBack(top).map((item) => item.id), [1, 3, 2])
  assert.deepEqual(sortAnnotationsBackToFront(top).map((item) => item.z_order), [0, 1, 2])

  const bottom = moveAnnotationToBack(top, 1)
  assert.deepEqual(sortAnnotationsFrontToBack(bottom).map((item) => item.id), [3, 2, 1])
  assert.deepEqual(sortAnnotationsBackToFront(bottom).map((item) => item.z_order), [0, 1, 2])
})

test('drag reorder inserts at the target foreground index', () => {
  const moved = moveAnnotationLayer([annotation(1, 0), annotation(2, 1), annotation(3, 2)], 1, 1)
  assert.deepEqual(sortAnnotationsFrontToBack(moved).map((item) => item.id), [3, 1, 2])
})

test('selection identity can remain stable across reorder', () => {
  const selectedId = 2
  const moved = moveAnnotationToFront([annotation(1, 0), annotation(2, 1), annotation(3, 2)], selectedId)
  assert.equal(moved.some((item) => item.id === selectedId), true)
})

test('new annotations can be assigned the next top layer', () => {
  assert.equal(nextTopLayerOrder([annotation(1, 0), annotation(2, 4)]), 5)
  assert.equal(nextTopLayerOrder([]), 0)
})

test('delete normalization removes layer holes without changing geometry or labels', () => {
  const normalized = normalizeAnnotationLayerOrder([annotation(1, 0), annotation(3, 9)])
  assert.deepEqual(normalized.map((item) => [item.id, item.label_id, item.z_order]), [[1, 1, 0], [3, 3, 1]])
  assert.deepEqual(normalized[1].points, [[0, 0], [10, 10]])
})

test('selected edit overlay does not mutate persisted layer order helpers', () => {
  const original = [annotation(1, 0), annotation(2, 1)]
  const sorted = sortAnnotationsBackToFront(original)
  assert.deepEqual(original.map((item) => item.z_order), [0, 1])
  assert.deepEqual(sorted.map((item) => item.z_order), [0, 1])
})

test('ObjectPanel source exposes drag handle and keyboard layer controls', () => {
  const source = readFileSync(new URL('../src/components/ObjectPanel.vue', import.meta.url), 'utf8')
  assert.match(source, /object-drag-handle/)
  assert.match(source, /moveAnnotationLayer/)
  assert.match(source, /layerUp/)
  assert.match(source, /layerDown/)
  assert.match(source, /layerTop/)
  assert.match(source, /layerBottom/)
})

test('save payload includes z_order and Canvas sorts before drawing', () => {
  const storeSource = readFileSync(new URL('../src/stores/annotation.ts', import.meta.url), 'utf8')
  const canvasSource = readFileSync(new URL('../src/components/AnnotationCanvas.vue', import.meta.url), 'utf8')
  assert.match(storeSource, /z_order:\s*annotation\.z_order/)
  assert.match(canvasSource, /sortAnnotationsBackToFront/)
})

test('image selector card styles preserve thumbnail dimensions', () => {
  const styles = readFileSync(new URL('../src/styles.css', import.meta.url), 'utf8')
  assert.match(styles, /grid-auto-rows:\s*max-content/)
  assert.match(styles, /aspect-ratio:\s*16\s*\/\s*9/)
  assert.match(styles, /object-fit:\s*contain/)
  assert.doesNotMatch(styles, /\.image-selector-thumb img\s*\{[^}]*object-fit:\s*cover/s)
})
