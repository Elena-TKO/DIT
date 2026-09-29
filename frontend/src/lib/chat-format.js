// Лёгкий Markdown для ответов помощника: абзацы, списки, **жирный**, _курсив_.
// Текст сначала экранируется целиком, поэтому HTML из ответа никогда не исполняется.

import { escapeHtml } from './map.js'

function inline(text) {
  return escapeHtml(text)
    .replace(/\*\*([^*]+?)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[\s(])_([^_]+?)_(?=[\s).,;:!?]|$)/g, '$1<em>$2</em>')
}

export function renderMarkdown(source) {
  const lines = String(source ?? '').replace(/\r\n/g, '\n').split('\n')
  const out = []
  let list = null   // 'ul' | 'ol'
  let para = []
  const flushPara = () => {
    if (para.length) out.push(`<p>${para.map(inline).join('<br>')}</p>`)
    para = []
  }
  const closeList = () => {
    if (list) out.push(`</${list}>`)
    list = null
  }
  for (const raw of lines) {
    const line = raw.trimEnd()
    const bullet = line.match(/^\s*[-•]\s+(.*)$/)
    const numbered = line.match(/^\s*\d+[.)]\s+(.*)$/)
    if (bullet || numbered) {
      flushPara()
      const kind = bullet ? 'ul' : 'ol'
      if (list !== kind) { closeList(); out.push(`<${kind}>`); list = kind }
      out.push(`<li>${inline((bullet || numbered)[1])}</li>`)
    } else if (!line.trim()) {
      flushPara()
      closeList()
    } else {
      closeList()
      para.push(line)
    }
  }
  flushPara()
  closeList()
  return out.join('')
}
