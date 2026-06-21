export const MIN_LABEL_COLOR_DISTANCE = 60

export const LABEL_COLOR_PALETTE = [
  '#ff7a1a',
  '#1f9fe5',
  '#22c55e',
  '#a855f7',
  '#ef4444',
  '#eab308',
  '#14b8a6',
  '#ec4899',
  '#6366f1',
  '#84cc16',
  '#f97316',
  '#06b6d4',
  '#8b5cf6',
  '#f43f5e',
  '#10b981',
  '#64748b',
]

export function normalizeHexColor(color: string | null | undefined): string | null {
  if (!color) {
    return null
  }

  const trimmed = color.trim()
  const match = /^#?([0-9a-fA-F]{6})$/.exec(trimmed)
  if (!match) {
    return null
  }

  return `#${match[1].toLowerCase()}`
}

export function hexToRgb(color: string): [number, number, number] {
  const normalized = normalizeHexColor(color)
  if (!normalized) {
    throw new Error(`Invalid hex color: ${color}`)
  }

  return [
    Number.parseInt(normalized.slice(1, 3), 16),
    Number.parseInt(normalized.slice(3, 5), 16),
    Number.parseInt(normalized.slice(5, 7), 16),
  ]
}

export function colorDistance(color1: string, color2: string): number {
  const [r1, g1, b1] = hexToRgb(color1)
  const [r2, g2, b2] = hexToRgb(color2)
  return Math.sqrt((r1 - r2) ** 2 + (g1 - g2) ** 2 + (b1 - b2) ** 2)
}

export function isColorConflict(color: string, usedColors: Iterable<string>): boolean {
  const normalized = normalizeHexColor(color)
  if (!normalized) {
    return true
  }

  for (const usedColor of usedColors) {
    const normalizedUsed = normalizeHexColor(usedColor)
    if (!normalizedUsed) {
      continue
    }
    if (colorDistance(normalized, normalizedUsed) < MIN_LABEL_COLOR_DISTANCE) {
      return true
    }
  }

  return false
}

export function pickDistinctLabelColor(preferredColor: string | null | undefined, usedColors: Iterable<string>): string {
  const normalizedPreferred = normalizeHexColor(preferredColor)
  if (normalizedPreferred && !isColorConflict(normalizedPreferred, usedColors)) {
    return normalizedPreferred
  }

  const usedSet = new Set(Array.from(usedColors, (color) => normalizeHexColor(color)).filter((color): color is string => Boolean(color)))
  for (const candidate of LABEL_COLOR_PALETTE) {
    if (!isColorConflict(candidate, usedSet)) {
      return candidate
    }
  }

  for (let i = 0; i < 128; i += 1) {
    const candidate = `#${Math.floor(Math.random() * 0xffffff)
      .toString(16)
      .padStart(6, '0')}`
    if (!isColorConflict(candidate, usedSet)) {
      return candidate
    }
  }

  return `#${Math.floor(Math.random() * 0xffffff)
    .toString(16)
    .padStart(6, '0')}`
}
