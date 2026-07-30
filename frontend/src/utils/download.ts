export function parseContentDispositionFilename(contentDisposition: string | null): string | null {
  if (!contentDisposition) {
    return null
  }

  const encodedMatch = contentDisposition.match(/filename\*\s*=\s*([^;]+)/i)
  if (encodedMatch) {
    const encodedValue = stripHeaderQuotes(encodedMatch[1].trim())
    const normalizedValue = encodedValue.replace(/^UTF-8''/i, '')
    try {
      return decodeURIComponent(normalizedValue)
    } catch {
      return normalizedValue
    }
  }

  const basicMatch = contentDisposition.match(/filename\s*=\s*([^;]+)/i)
  if (!basicMatch) {
    return null
  }

  return stripHeaderQuotes(basicMatch[1].trim())
}

function stripHeaderQuotes(value: string) {
  return value.replace(/^["']|["']$/g, '')
}

export type DownloadBlobOptions = {
  blob: Blob
  filename: string
  documentLike?: Document
  urlLike?: Pick<typeof URL, 'createObjectURL' | 'revokeObjectURL'>
}

export function downloadBlobWithFilename(options: DownloadBlobOptions) {
  const documentLike = options.documentLike ?? document
  const urlLike = options.urlLike ?? URL
  const objectUrl = urlLike.createObjectURL(options.blob)
  const link = documentLike.createElement('a')
  link.href = objectUrl
  link.download = options.filename
  documentLike.body.appendChild(link)
  link.click()
  link.remove()
  setTimeout(() => {
    urlLike.revokeObjectURL(objectUrl)
  }, 0)
}
