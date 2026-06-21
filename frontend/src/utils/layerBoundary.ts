import { clonePoints, simplifyPolygonRdp } from './polygon'

export type Point = number[]

const DEFAULT_SAMPLE_STEP = 2
const DEFAULT_SIMPLIFY_EPSILON = 0.8

export function rasterizePolygonToMask(points: Point[], width: number, height: number): Uint8ClampedArray {
  const safeWidth = Math.max(1, Math.round(width))
  const safeHeight = Math.max(1, Math.round(height))
  const canvas = createRasterCanvas(safeWidth, safeHeight)
  const context = canvas.getContext('2d', { willReadFrequently: true }) as CanvasRenderingContext2D | OffscreenCanvasRenderingContext2D | null
  if (!context) {
    return new Uint8ClampedArray(safeWidth * safeHeight * 4)
  }

  context.clearRect(0, 0, safeWidth, safeHeight)
  context.fillStyle = '#ffffff'
  context.beginPath()
  points.forEach((point, index) => {
    const x = Number(point[0])
    const y = Number(point[1])
    if (index === 0) {
      context.moveTo(x, y)
    } else {
      context.lineTo(x, y)
    }
  })
  context.closePath()
  context.fill()

  return context.getImageData(0, 0, safeWidth, safeHeight).data
}

export function extractTopBoundaryFromPolygon(points: Point[], imageWidth: number, imageHeight: number): Point[] {
  if (points.length < 3) {
    return []
  }

  const width = Math.max(1, Math.round(imageWidth))
  const height = Math.max(1, Math.round(imageHeight))
  const mask = rasterizePolygonToMask(points, width, height)
  const boundary: Point[] = []

  for (let x = 0; x < width; x += 1) {
    for (let y = 0; y < height; y += 1) {
      const alpha = mask[(y * width + x) * 4 + 3]
      if (alpha > 0) {
        boundary.push([x, y])
        break
      }
    }
  }

  if (boundary.length < 2) {
    return boundary
  }

  const simplified = simplifyGeneratedPolygon(boundary, DEFAULT_SIMPLIFY_EPSILON)
  return simplified.length >= 2 ? simplified : boundary
}

export function resamplePolylineByX(
  points: Point[],
  xStart: number,
  xEnd: number,
  sampleStep = DEFAULT_SAMPLE_STEP,
): Point[] {
  const normalizedPoints = normalizePolylineForSampling(points)
  if (normalizedPoints.length < 2) {
    return []
  }

  const samples = samplePolylineAcrossIntegerX(normalizedPoints)
  if (samples.size === 0) {
    return []
  }

  const safeStart = Math.ceil(Math.min(xStart, xEnd))
  const safeEnd = Math.floor(Math.max(xStart, xEnd))
  const safeStep = Math.max(1, Math.round(sampleStep))
  const resampled: Point[] = []

  if (samples.has(safeStart)) {
    resampled.push([safeStart, samples.get(safeStart)!])
  }

  for (let x = safeStart; x <= safeEnd; x += safeStep) {
    const y = samples.get(x)
    if (y !== undefined) {
      resampled.push([x, y])
    }
  }

  if ((resampled.length === 0 || resampled[resampled.length - 1][0] !== safeEnd) && samples.has(safeEnd)) {
    resampled.push([safeEnd, samples.get(safeEnd)!])
  }

  return removeDuplicatePoints(resampled)
}

export function buildLayerPolygonFromTopAndBottom(
  topLinePoints: Point[],
  bottomBoundaryPoints: Point[],
  sampleStep = DEFAULT_SAMPLE_STEP,
): {
  points: Point[]
  topCurve: Point[]
  bottomCurve: Point[]
  xStart: number
  xEnd: number
} {
  if (topLinePoints.length < 2 || bottomBoundaryPoints.length < 2) {
    throw new Error('At least two points are required to build a layer polygon.')
  }

  const xStart = Math.ceil(Math.max(minPointX(topLinePoints), minPointX(bottomBoundaryPoints)))
  const xEnd = Math.floor(Math.min(maxPointX(topLinePoints), maxPointX(bottomBoundaryPoints)))
  if (xEnd - xStart < Math.max(2, sampleStep * 2)) {
    throw new Error('The drawn upper boundary does not overlap enough with the selected lower polygon.')
  }

  const topCurve = resamplePolylineByX(topLinePoints, xStart, xEnd, sampleStep)
  const bottomCurve = resamplePolylineByX(bottomBoundaryPoints, xStart, xEnd, sampleStep)
  const topByX = new Map(topCurve.map((point) => [Math.round(point[0]), Number(point[1])]))
  const bottomByX = new Map(bottomCurve.map((point) => [Math.round(point[0]), Number(point[1])]))
  const commonXs = [...topByX.keys()]
    .filter((x) => bottomByX.has(x))
    .sort((left, right) => left - right)

  if (commonXs.length < 3) {
    throw new Error('Cannot create layer polygon. Please make sure the drawn upper boundary overlaps with the selected lower polygon.')
  }

  const alignedTop = commonXs.map((x) => [x, topByX.get(x)!] as Point)
  const alignedBottom = commonXs.map((x) => [x, bottomByX.get(x)!] as Point)

  if (alignedTop.some((point, index) => point[1] >= alignedBottom[index][1])) {
    throw new Error('The drawn upper boundary must stay above the selected lower polygon boundary.')
  }

  const polygon = removeDuplicatePoints([
    ...alignedTop,
    ...clonePoints(alignedBottom).reverse(),
  ])
  const simplified = simplifyGeneratedPolygon(polygon, DEFAULT_SIMPLIFY_EPSILON)
  const nextPolygon = simplified.length >= 3 ? simplified : polygon

  if (nextPolygon.length < 3) {
    throw new Error('Cannot create layer polygon. Please draw a longer upper boundary.')
  }

  return {
    points: nextPolygon,
    topCurve: alignedTop,
    bottomCurve: alignedBottom,
    xStart: commonXs[0],
    xEnd: commonXs[commonXs.length - 1],
  }
}

export function removeDuplicatePoints(points: Point[]): Point[] {
  const deduped: Point[] = []
  for (const point of points) {
    if (!Array.isArray(point) || point.length < 2) {
      continue
    }

    const normalized: Point = [Number(point[0]), Number(point[1])]
    if (!Number.isFinite(normalized[0]) || !Number.isFinite(normalized[1])) {
      continue
    }

    const previous = deduped[deduped.length - 1]
    if (!previous || previous[0] !== normalized[0] || previous[1] !== normalized[1]) {
      deduped.push(normalized)
    }
  }

  if (deduped.length >= 2) {
    const first = deduped[0]
    const last = deduped[deduped.length - 1]
    if (first[0] === last[0] && first[1] === last[1]) {
      deduped.pop()
    }
  }

  return deduped
}

export function simplifyGeneratedPolygon(points: Point[], epsilon = DEFAULT_SIMPLIFY_EPSILON): Point[] {
  const deduped = removeDuplicatePoints(points)
  if (deduped.length <= 3 || epsilon <= 0) {
    return clonePoints(deduped)
  }

  const simplified = removeDuplicatePoints(simplifyPolygonRdp(deduped, epsilon))
  return simplified.length >= 3 ? simplified : clonePoints(deduped)
}

function createRasterCanvas(width: number, height: number): OffscreenCanvas | HTMLCanvasElement {
  if (typeof OffscreenCanvas !== 'undefined') {
    return new OffscreenCanvas(width, height)
  }

  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  return canvas
}

function normalizePolylineForSampling(points: Point[]): Point[] {
  const cloned = clonePoints(points)
  if (cloned.length <= 1) {
    return cloned
  }

  const oriented = cloned[0][0] <= cloned[cloned.length - 1][0]
    ? cloned
    : cloned.reverse()

  return oriented.sort((left, right) => left[0] - right[0] || left[1] - right[1])
}

function samplePolylineAcrossIntegerX(points: Point[]): Map<number, number> {
  const samples = new Map<number, number>()

  function setSample(x: number, y: number) {
    if (!Number.isFinite(x) || !Number.isFinite(y)) {
      return
    }
    const roundedX = Math.round(x)
    const existing = samples.get(roundedX)
    samples.set(roundedX, existing === undefined ? y : Math.min(existing, y))
  }

  for (let index = 0; index < points.length - 1; index += 1) {
    const start = points[index]
    const end = points[index + 1]
    const minX = Math.min(start[0], end[0])
    const maxX = Math.max(start[0], end[0])

    if (minX === maxX) {
      setSample(minX, Math.min(start[1], end[1]))
      continue
    }

    setSample(start[0], start[1])
    setSample(end[0], end[1])

    const fromX = Math.ceil(minX)
    const toX = Math.floor(maxX)
    for (let x = fromX; x <= toX; x += 1) {
      const t = (x - start[0]) / (end[0] - start[0])
      const y = start[1] + (end[1] - start[1]) * t
      setSample(x, y)
    }
  }

  return samples
}

function minPointX(points: Point[]): number {
  return Math.min(...points.map((point) => Number(point[0])))
}

function maxPointX(points: Point[]): number {
  return Math.max(...points.map((point) => Number(point[0])))
}
