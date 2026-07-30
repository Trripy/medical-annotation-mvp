import type { AnnotationObject } from '../stores/annotation'

export function annotationLayerOrder(annotation: Pick<AnnotationObject, 'z_order'>): number {
  const value = annotation.z_order
  return typeof value === 'number' && Number.isFinite(value) ? value : 0
}

export function compareAnnotationsBackToFront(left: AnnotationObject, right: AnnotationObject): number {
  return annotationLayerOrder(left) - annotationLayerOrder(right) || compareAnnotationIds(left.id, right.id)
}

export function compareAnnotationsFrontToBack(left: AnnotationObject, right: AnnotationObject): number {
  return annotationLayerOrder(right) - annotationLayerOrder(left) || compareAnnotationIds(right.id, left.id)
}

export function sortAnnotationsBackToFront<T extends AnnotationObject>(annotations: T[]): T[] {
  return annotations.slice().sort(compareAnnotationsBackToFront)
}

export function sortAnnotationsFrontToBack<T extends AnnotationObject>(annotations: T[]): T[] {
  return annotations.slice().sort(compareAnnotationsFrontToBack)
}

export function normalizeAnnotationLayerOrder<T extends AnnotationObject>(annotations: T[]): T[] {
  return sortAnnotationsBackToFront(annotations).map((annotation, index) => ({
    ...annotation,
    z_order: index,
  }))
}

export function nextTopLayerOrder(annotations: AnnotationObject[]): number {
  if (annotations.length === 0) {
    return 0
  }
  return Math.max(...annotations.map(annotationLayerOrder)) + 1
}

export function moveAnnotationLayer(
  annotations: AnnotationObject[],
  annotationId: number | string,
  targetFrontIndex: number,
): AnnotationObject[] {
  const frontToBack = sortAnnotationsFrontToBack(annotations)
  const currentIndex = frontToBack.findIndex((annotation) => annotation.id === annotationId)
  if (currentIndex < 0) {
    return annotations
  }

  const [moved] = frontToBack.splice(currentIndex, 1)
  const nextIndex = Math.max(0, Math.min(targetFrontIndex, frontToBack.length))
  frontToBack.splice(nextIndex, 0, moved)
  return assignLayerOrderInCurrentOrder(frontToBack.slice().reverse())
}

export function moveAnnotationLayerByStep(
  annotations: AnnotationObject[],
  annotationId: number | string,
  step: -1 | 1,
): AnnotationObject[] {
  const frontToBack = sortAnnotationsFrontToBack(annotations)
  const currentIndex = frontToBack.findIndex((annotation) => annotation.id === annotationId)
  if (currentIndex < 0) {
    return annotations
  }
  return moveAnnotationLayer(annotations, annotationId, currentIndex + step)
}

export function moveAnnotationToFront(annotations: AnnotationObject[], annotationId: number | string): AnnotationObject[] {
  return moveAnnotationLayer(annotations, annotationId, 0)
}

export function moveAnnotationToBack(annotations: AnnotationObject[], annotationId: number | string): AnnotationObject[] {
  return moveAnnotationLayer(annotations, annotationId, annotations.length - 1)
}

function compareAnnotationIds(left: number | string, right: number | string): number {
  const leftNumber = typeof left === 'number' ? left : Number.NaN
  const rightNumber = typeof right === 'number' ? right : Number.NaN
  if (Number.isFinite(leftNumber) && Number.isFinite(rightNumber)) {
    return leftNumber - rightNumber
  }
  return String(left).localeCompare(String(right))
}

function assignLayerOrderInCurrentOrder<T extends AnnotationObject>(backToFrontAnnotations: T[]): T[] {
  return backToFrontAnnotations.map((annotation, index) => ({
    ...annotation,
    z_order: index,
  }))
}
