import type { AnnotationObject } from '../stores/annotation'

export const MAX_POLYGON_SMOOTHING = 100

export function clonePoints(points: number[][]): number[][] {
  return points.map((point) => [Number(point[0]), Number(point[1])])
}

export function clampPolygonSmoothValue(value: number): number {
  if (!Number.isFinite(value)) {
    return 0
  }
  return Math.max(0, Math.min(MAX_POLYGON_SMOOTHING, Math.round(value)))
}

export function getPolygonRawPoints(annotation: AnnotationObject): number[][] {
  const rawPoints = annotation.attributes?.raw_points
  if (!Array.isArray(rawPoints)) {
    return clonePoints(annotation.points)
  }

  const normalized = rawPoints
    .filter((point): point is number[] => Array.isArray(point) && point.length >= 2)
    .map((point) => [Number(point[0]), Number(point[1])])
    .filter((point) => Number.isFinite(point[0]) && Number.isFinite(point[1]))

  return normalized.length >= 3 ? normalized : clonePoints(annotation.points)
}

export function getPolygonSmoothValue(annotation: AnnotationObject): number {
  const value = Number(annotation.attributes?.smooth_value ?? annotation.attributes?.smooth_epsilon ?? 0)
  return clampPolygonSmoothValue(value)
}

export function buildPolygonSmoothingAttributes(
  rawPoints: number[][],
  smoothValue: number,
  existingAttributes?: Record<string, unknown> | null,
): Record<string, unknown> {
  const attributes = existingAttributes && typeof existingAttributes === 'object'
    ? { ...existingAttributes }
    : {}

  delete attributes.smooth_epsilon

  return {
    ...attributes,
    raw_points: clonePoints(rawPoints),
    smooth_value: clampPolygonSmoothValue(smoothValue),
  }
}

export function normalizeAnnotationObject(annotation: AnnotationObject): AnnotationObject {
  const normalizedPoints = clonePoints(annotation.points)
  const attributes = annotation.attributes && typeof annotation.attributes === 'object'
    ? { ...annotation.attributes }
    : annotation.attributes ?? null

  if (annotation.shape_type !== 'polygon') {
    return {
      ...annotation,
      points: normalizedPoints,
      attributes,
    }
  }

  const normalizedAnnotation = {
    ...annotation,
    points: normalizedPoints,
    attributes,
  }

  return {
    ...normalizedAnnotation,
    attributes: buildPolygonSmoothingAttributes(
      getPolygonRawPoints(normalizedAnnotation),
      getPolygonSmoothValue(normalizedAnnotation),
      attributes,
    ),
  }
}

export function normalizeAnnotationObjects(annotations: AnnotationObject[]): AnnotationObject[] {
  return annotations.map(normalizeAnnotationObject)
}

export function sliderValueToSmoothEpsilon(sliderValue: number, imageWidth: number | null, imageHeight: number | null): number {
  const width = imageWidth ?? 1
  const height = imageHeight ?? 1
  const imageDiag = Math.sqrt(width * width + height * height)
  const clampedSlider = Math.max(0, Math.min(MAX_POLYGON_SMOOTHING, sliderValue))
  return imageDiag * (clampedSlider / MAX_POLYGON_SMOOTHING) * 0.01
}

export function smoothEpsilonToSliderValue(epsilon: number, imageWidth: number | null, imageHeight: number | null): number {
  const width = imageWidth ?? 1
  const height = imageHeight ?? 1
  const imageDiag = Math.sqrt(width * width + height * height)
  if (!Number.isFinite(epsilon) || epsilon <= 0 || imageDiag <= 0) {
    return 0
  }
  const slider = (epsilon / imageDiag) / 0.01 * MAX_POLYGON_SMOOTHING
  return Math.max(0, Math.min(MAX_POLYGON_SMOOTHING, Math.round(slider)))
}

export function simplifyPolygonRdp(points: number[][], epsilon: number): number[][] {
  const uniquePoints = dedupeConsecutivePoints(points)
  if (uniquePoints.length <= 3 || epsilon <= 0) {
    return clonePoints(uniquePoints)
  }

  const closedPoints = isClosedPolygon(uniquePoints)
    ? uniquePoints.slice(0, -1)
    : uniquePoints

  if (closedPoints.length <= 3) {
    return clonePoints(closedPoints)
  }

  const [startIndex, endIndex] = findApproximateAnchorPair(closedPoints)
  const forward = collectWrappedPoints(closedPoints, startIndex, endIndex)
  const backward = collectWrappedPoints(closedPoints, endIndex, startIndex)
  const simplifiedForward = simplifyPolylineRdp(forward, epsilon)
  const simplifiedBackward = simplifyPolylineRdp(backward, epsilon)
  const merged = dedupeConsecutivePoints([
    ...simplifiedForward.slice(0, -1),
    ...simplifiedBackward.slice(0, -1),
  ])

  return merged.length >= 3 ? merged : clonePoints(closedPoints)
}

function simplifyPolylineRdp(points: number[][], epsilon: number): number[][] {
  if (points.length <= 2) {
    return clonePoints(points)
  }

  let maxDistance = -1
  let splitIndex = -1
  const start = points[0]
  const end = points[points.length - 1]

  for (let index = 1; index < points.length - 1; index += 1) {
    const distance = perpendicularDistance(points[index], start, end)
    if (distance > maxDistance) {
      maxDistance = distance
      splitIndex = index
    }
  }

  if (maxDistance <= epsilon || splitIndex === -1) {
    return [clonePoint(start), clonePoint(end)]
  }

  const left = simplifyPolylineRdp(points.slice(0, splitIndex + 1), epsilon)
  const right = simplifyPolylineRdp(points.slice(splitIndex), epsilon)
  return [...left.slice(0, -1), ...right]
}

function perpendicularDistance(point: number[], start: number[], end: number[]): number {
  const dx = end[0] - start[0]
  const dy = end[1] - start[1]
  if (dx === 0 && dy === 0) {
    return Math.hypot(point[0] - start[0], point[1] - start[1])
  }

  const numerator = Math.abs(dy * point[0] - dx * point[1] + end[0] * start[1] - end[1] * start[0])
  const denominator = Math.sqrt(dx * dx + dy * dy)
  return denominator === 0 ? 0 : numerator / denominator
}

function dedupeConsecutivePoints(points: number[][]): number[][] {
  const deduped: number[][] = []
  for (const point of points) {
    if (!Array.isArray(point) || point.length < 2) {
      continue
    }
    const normalized = [Number(point[0]), Number(point[1])]
    if (!Number.isFinite(normalized[0]) || !Number.isFinite(normalized[1])) {
      continue
    }
    const previous = deduped[deduped.length - 1]
    if (!previous || previous[0] !== normalized[0] || previous[1] !== normalized[1]) {
      deduped.push(normalized)
    }
  }
  return deduped
}

function isClosedPolygon(points: number[][]): boolean {
  if (points.length < 2) {
    return false
  }
  const first = points[0]
  const last = points[points.length - 1]
  return first[0] === last[0] && first[1] === last[1]
}

function findApproximateAnchorPair(points: number[][]): [number, number] {
  let anchorA = 0
  let anchorB = farthestPointIndex(points, anchorA)
  anchorA = farthestPointIndex(points, anchorB)
  if (anchorA === anchorB) {
    anchorB = (anchorA + Math.floor(points.length / 2)) % points.length
  }
  return [anchorA, anchorB]
}

function farthestPointIndex(points: number[][], fromIndex: number): number {
  let bestIndex = fromIndex
  let bestDistance = -1
  const [x1, y1] = points[fromIndex]
  for (let index = 0; index < points.length; index += 1) {
    const [x2, y2] = points[index]
    const distance = (x2 - x1) ** 2 + (y2 - y1) ** 2
    if (distance > bestDistance) {
      bestDistance = distance
      bestIndex = index
    }
  }
  return bestIndex
}

function collectWrappedPoints(points: number[][], startIndex: number, endIndex: number): number[][] {
  const collected: number[][] = []
  let index = startIndex
  while (true) {
    collected.push(clonePoint(points[index]))
    if (index === endIndex) {
      break
    }
    index = (index + 1) % points.length
  }
  return collected
}

function clonePoint(point: number[]): number[] {
  return [Number(point[0]), Number(point[1])]
}
