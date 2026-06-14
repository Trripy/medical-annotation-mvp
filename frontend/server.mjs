import { createReadStream, existsSync, statSync } from 'node:fs'
import { createServer } from 'node:http'
import { extname, join, normalize } from 'node:path'

const root = join(process.cwd(), 'dist')
const port = Number(process.env.PORT || 5173)
const host = process.env.HOST || '0.0.0.0'

const contentTypes = new Map([
  ['.css', 'text/css; charset=utf-8'],
  ['.html', 'text/html; charset=utf-8'],
  ['.ico', 'image/x-icon'],
  ['.js', 'text/javascript; charset=utf-8'],
  ['.json', 'application/json; charset=utf-8'],
  ['.png', 'image/png'],
  ['.svg', 'image/svg+xml'],
  ['.webp', 'image/webp'],
])

function resolvePath(url) {
  const pathname = decodeURIComponent(new URL(url, `http://${host}:${port}`).pathname)
  const safePath = normalize(pathname).replace(/^(\.\.[/\\])+/, '')
  const candidate = join(root, safePath)

  if (existsSync(candidate) && statSync(candidate).isFile()) {
    return candidate
  }

  return join(root, 'index.html')
}

createServer((request, response) => {
  const filePath = resolvePath(request.url || '/')
  const contentType = contentTypes.get(extname(filePath)) || 'application/octet-stream'
  response.writeHead(200, {
    'Cache-Control': filePath.endsWith('index.html') ? 'no-cache' : 'public, max-age=3600',
    'Content-Type': contentType,
  })
  createReadStream(filePath).pipe(response)
}).listen(port, host, () => {
  console.log(`Static frontend listening on http://${host}:${port}`)
})
