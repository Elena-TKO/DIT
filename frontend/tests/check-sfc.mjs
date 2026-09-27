// Статическая проверка .vue-файлов без сборки: синтаксис <script setup> и выражений шаблона,
// баланс тегов, необъявленные идентификаторы, импорты, компоненты, props и события.
// Запуск: node tests/check-sfc.mjs   (нужен пакет typescript)
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { createRequire } from 'node:module'

const require = createRequire(import.meta.url)
const ts = require('typescript')

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', 'src')
const VOID = new Set(['input', 'img', 'br', 'hr', 'meta', 'link', 'source', 'col', 'area', 'wbr'])
const TEMPLATE_GLOBALS = new Set(('Infinity,undefined,NaN,isFinite,isNaN,parseFloat,parseInt,decodeURI,' +
  'decodeURIComponent,encodeURI,encodeURIComponent,Math,Number,Date,Array,Object,Boolean,String,RegExp,Map,Set,' +
  'JSON,Intl,BigInt,console,Error,$event,$attrs,$slots,$props,$emit,true,false,null,this').split(','))
const GLOBAL_COMPONENTS = new Set(['RouterLink', 'RouterView'])
const KNOWN_ATTRS = new Set(['class', 'style', 'key', 'ref', 'id', 'title'])
const errors = []

const camel = (s) => s.replace(/-([a-z])/g, (_, c) => c.toUpperCase())
const err = (file, msg) => errors.push(`${path.relative(ROOT, file)}: ${msg}`)

function parse(code, file, kind) {
  const sf = ts.createSourceFile(file + (kind ? '.' + kind + '.ts' : ''), code, ts.ScriptTarget.ES2022, true, ts.ScriptKind.JS)
  return { sf, diags: sf.parseDiagnostics || [] }
}

function splitSfc(text) {
  const script = text.match(/<script setup>([\s\S]*?)<\/script>/)
  const tStart = text.indexOf('<template>')
  const tEnd = text.lastIndexOf('</template>')
  return {
    script: script ? script[1] : '',
    template: tStart >= 0 ? text.slice(tStart + '<template>'.length, tEnd) : '',
  }
}

// ---------------------------------------------------------------- анализ скрипта
function bindingNames(nameNode, out) {
  if (ts.isIdentifier(nameNode)) out.add(nameNode.text)
  else if (ts.isObjectBindingPattern(nameNode) || ts.isArrayBindingPattern(nameNode)) {
    for (const el of nameNode.elements) if (!ts.isOmittedExpression(el)) bindingNames(el.name, out)
  }
}

function analyzeScript(file, code) {
  const { sf, diags } = parse(code, file)
  for (const d of diags) err(file, `синтаксис script: ${ts.flattenDiagnosticMessageText(d.messageText, ' ')}`)
  const bindings = new Set()
  const imports = []
  let props = {}
  let emits = null
  const visitCall = (node) => {
    if (ts.isCallExpression(node) && ts.isIdentifier(node.expression)) {
      const fn = node.expression.text
      if (fn === 'defineProps' && node.arguments[0] && ts.isObjectLiteralExpression(node.arguments[0])) {
        for (const p of node.arguments[0].properties) {
          const name = p.name.text
          let required = false
          if (ts.isPropertyAssignment(p) && ts.isObjectLiteralExpression(p.initializer)) {
            required = p.initializer.properties.some((q) => q.name?.text === 'required' &&
              q.initializer.kind === ts.SyntaxKind.TrueKeyword)
          }
          props[name] = { required }
        }
      }
      if (fn === 'defineEmits' && node.arguments[0] && ts.isArrayLiteralExpression(node.arguments[0])) {
        emits = node.arguments[0].elements.map((e) => e.text)
      }
    }
    ts.forEachChild(node, visitCall)
  }
  for (const st of sf.statements) {
    if (ts.isImportDeclaration(st)) {
      const from = st.moduleSpecifier.text
      const clause = st.importClause
      const named = []
      if (clause?.name) { bindings.add(clause.name.text); named.push('default') }
      if (clause?.namedBindings && ts.isNamedImports(clause.namedBindings)) {
        for (const el of clause.namedBindings.elements) {
          bindings.add(el.name.text)
          named.push((el.propertyName || el.name).text)
        }
      }
      imports.push({ from, named, defaultName: clause?.name?.text })
    } else if (ts.isVariableStatement(st)) {
      for (const d of st.declarationList.declarations) bindingNames(d.name, bindings)
    } else if (ts.isFunctionDeclaration(st) && st.name) {
      bindings.add(st.name.text)
    }
    visitCall(st)
  }
  for (const p of Object.keys(props)) bindings.add(p)
  checkIdentifiersInScript(file, sf, bindings)
  return { bindings, imports, props, emits }
}

function checkIdentifiersInScript(file, sf, bindings) {
  // В скрипте проверяем только обращения к явно необъявленным свободным переменным верхнего уровня
  const browserGlobals = new Set(['window', 'document', 'navigator', 'localStorage', 'sessionStorage', 'fetch', 'URL', 'URLSearchParams', 'FormData', 'Blob', 'File', 'AbortController',
    'setInterval', 'clearInterval', 'setTimeout', 'clearTimeout', 'Promise', 'Error', 'Math', 'Number', 'Date', 'Array',
    'Object', 'Boolean', 'String', 'JSON', 'Set', 'Map', 'console', 'undefined', 'Infinity', 'NaN', 'defineProps',
    'defineEmits', 'defineExpose', 'isNaN', 'parseInt'])
  freeIdentifiers(sf, new Set()).forEach((name) => {
    if (!bindings.has(name) && !browserGlobals.has(name)) err(file, `script: необъявленный идентификатор «${name}»`)
  })
}

// Свободные идентификаторы выражения (с учётом параметров стрелочных функций и локальных объявлений)
function freeIdentifiers(root, initialScope) {
  const found = new Set()
  const walk = (node, scope) => {
    if (ts.isArrowFunction(node) || ts.isFunctionExpression(node) || ts.isFunctionDeclaration(node)) {
      const inner = new Set(scope)
      if (node.name) inner.add(node.name.text)
      node.parameters.forEach((p) => bindingNames(p.name, inner))
      // объявления внутри тела функции
      const collect = (n) => {
        if (ts.isVariableDeclaration(n)) bindingNames(n.name, inner)
        if (ts.isFunctionDeclaration(n) && n.name) inner.add(n.name.text)
        if (!ts.isArrowFunction(n) && !ts.isFunctionExpression(n)) ts.forEachChild(n, collect)
      }
      if (node.body) ts.forEachChild(node.body, collect)
      node.parameters.forEach((p) => p.initializer && walk(p.initializer, inner))
      if (node.body) walk(node.body, inner)
      return
    }
    if (ts.isCatchClause(node) && node.variableDeclaration) {
      const inner = new Set(scope)
      bindingNames(node.variableDeclaration.name, inner)
      walk(node.block, inner)
      return
    }
    if (ts.isForOfStatement(node) || ts.isForInStatement(node) || ts.isForStatement(node)) {
      const inner = new Set(scope)
      const init = node.initializer
      if (init && ts.isVariableDeclarationList(init)) init.declarations.forEach((d) => bindingNames(d.name, inner))
      ts.forEachChild(node, (c) => walk(c, inner))
      return
    }
    if (ts.isIdentifier(node)) {
      const parent = node.parent
      const isPropName = parent && ((ts.isPropertyAccessExpression(parent) && parent.name === node) ||
        (ts.isPropertyAssignment(parent) && parent.name === node) ||
        (ts.isMethodDeclaration(parent) && parent.name === node) ||
        (ts.isBindingElement(parent) && parent.propertyName === node) ||
        (ts.isVariableDeclaration(parent) && parent.name === node) ||
        (ts.isBindingElement(parent) && parent.name === node) ||
        (ts.isFunctionDeclaration(parent) && parent.name === node) ||
        (ts.isParameter(parent) && parent.name === node) ||
        ts.isImportSpecifier(parent) || ts.isImportClause(parent) || ts.isLabeledStatement(parent) ||
        ts.isBreakOrContinueStatement(parent))
      if (!isPropName && !scope.has(node.text)) found.add(node.text)
      return
    }
    ts.forEachChild(node, (c) => walk(c, scope))
  }
  // верхний уровень: сначала локальные объявления файла
  const scope = new Set(initialScope)
  if (ts.isSourceFile(root)) {
    root.statements.forEach((st) => {
      if (ts.isVariableStatement(st)) st.declarationList.declarations.forEach((d) => bindingNames(d.name, scope))
      if (ts.isFunctionDeclaration(st) && st.name) scope.add(st.name.text)
      if (ts.isImportDeclaration(st)) {
        const c = st.importClause
        if (c?.name) scope.add(c.name.text)
        if (c?.namedBindings && ts.isNamedImports(c.namedBindings)) c.namedBindings.elements.forEach((e) => scope.add(e.name.text))
      }
    })
  }
  walk(root, scope)
  return found
}

// ---------------------------------------------------------------- шаблон
function tokenize(file, html) {
  const tokens = []
  let i = 0
  while (i < html.length) {
    if (html.startsWith('<!--', i)) { i = html.indexOf('-->', i) + 3; continue }
    if (html[i] === '<' && /[a-zA-Z/]/.test(html[i + 1] || '')) {
      const closing = html[i + 1] === '/'
      let j = i + (closing ? 2 : 1)
      const nameMatch = html.slice(j).match(/^[A-Za-z][\w-]*/)
      if (!nameMatch) { i++; continue }
      const name = nameMatch[0]
      j += name.length
      const attrs = []
      let quote = null
      let buf = ''
      const line = html.slice(0, i).split('\n').length
      while (j < html.length) {
        const ch = html[j]
        if (quote) {
          buf += ch
          if (ch === quote) quote = null
        } else if (ch === '"' || ch === "'") {
          quote = ch
          buf += ch
        } else if (ch === '>') {
          break
        } else {
          buf += ch
        }
        j++
      }
      if (j >= html.length) { err(file, `незакрытый тег <${name}> (строка шаблона ${line})`); break }
      const selfClosing = buf.trimEnd().endsWith('/')
      const re = /([:@#]?[\w\-.:\[\]]+)(?:\s*=\s*("([^"]*)"|'([^']*)'))?/g
      let m
      const attrText = selfClosing ? buf.trimEnd().slice(0, -1) : buf
      while ((m = re.exec(attrText))) attrs.push({ name: m[1], value: m[3] ?? m[4] ?? null })
      tokens.push({ type: closing ? 'close' : 'open', name, attrs, selfClosing, line })
      i = j + 1
      continue
    }
    const next = html.indexOf('<', i + 1)
    const text = html.slice(i, next === -1 ? html.length : next)
    tokens.push({ type: 'text', text, line: html.slice(0, i).split('\n').length })
    i = next === -1 ? html.length : next
  }
  return tokens
}

function checkExpression(file, code, scope, where, asStatement = false) {
  const src = asStatement ? code : `(${code});`
  const { sf, diags } = parse(src, file, 'expr')
  if (diags.length) {
    err(file, `${where}: синтаксис «${code}»: ${ts.flattenDiagnosticMessageText(diags[0].messageText, ' ')}`)
    return
  }
  for (const name of freeIdentifiers(sf, new Set())) {
    if (!scope.has(name) && !TEMPLATE_GLOBALS.has(name)) err(file, `${where}: необъявленный «${name}» в «${code}»`)
  }
}

function analyzeTemplate(file, html, info, components) {
  const tokens = tokenize(file, html)
  const stack = []
  const scopes = [new Set(info.bindings)]
  for (const tok of tokens) {
    const scope = scopes[scopes.length - 1]
    if (tok.type === 'text') {
      for (const m of tok.text.matchAll(/\{\{([\s\S]*?)\}\}/g)) checkExpression(file, m[1].trim(), scope, `строка ${tok.line}`)
      continue
    }
    if (tok.type === 'close') {
      const top = stack.pop()
      if (!top || top !== tok.name) err(file, `строка ${tok.line}: </${tok.name}> не соответствует <${top}>`)
      scopes.pop()
      continue
    }
    const local = new Set(scope)
    const where = `строка ${tok.line} <${tok.name}>`
    const vfor = tok.attrs.find((a) => a.name === 'v-for')
    if (vfor) {
      const m = vfor.value.match(/^\s*(?:\(([^)]*)\)|([\w$]+))\s+(?:in|of)\s+([\s\S]+)$/)
      if (!m) err(file, `${where}: некорректный v-for «${vfor.value}»`)
      else {
        checkExpression(file, m[3], scope, where)
        ;(m[1] || m[2]).split(',').map((s) => s.trim()).filter(Boolean).forEach((a) => local.add(a))
      }
      if (!tok.attrs.some((a) => a.name === ':key' || a.name === 'v-bind:key')) err(file, `${where}: v-for без :key`)
    }
    for (const a of tok.attrs) {
      if (a.name === 'v-for' || a.value === null) continue
      if (a.name.startsWith('@') || a.name.startsWith('v-on:')) {
        const v = a.value.trim()
        const isRef = /^[\w$.]+$/.test(v)
        checkExpression(file, isRef ? v : v, local, `${where} ${a.name}`, !isRef)
      } else if (a.name.startsWith(':') || a.name.startsWith('v-bind:') || ['v-if', 'v-else-if', 'v-show', 'v-model', 'v-html', 'v-text'].includes(a.name) || a.name.startsWith('v-model')) {
        checkExpression(file, a.value, local, `${where} ${a.name}`)
      }
    }
    // компоненты
    if (/^[A-Z]/.test(tok.name)) {
      if (!GLOBAL_COMPONENTS.has(tok.name) && !info.bindings.has(tok.name)) err(file, `${where}: компонент не импортирован`)
      const target = components[tok.name]
      if (target) {
        const given = new Set()
        for (const a of tok.attrs) {
          if (a.name.startsWith('@')) {
            const ev = a.name.slice(1)
            if (!target.emits || !target.emits.includes(ev)) err(file, `${where}: событие «${ev}» не объявлено в defineEmits`)
            continue
          }
          const raw = a.name.replace(/^(:|v-bind:)/, '')
          if (KNOWN_ATTRS.has(raw) || raw.startsWith('v-')) continue
          const prop = camel(raw)
          given.add(prop)
          if (!(prop in target.props)) err(file, `${where}: у компонента нет prop «${prop}»`)
        }
        for (const [p, meta] of Object.entries(target.props)) {
          if (meta.required && !given.has(p)) err(file, `${where}: не передан обязательный prop «${p}»`)
        }
      }
    }
    if (!VOID.has(tok.name) && !tok.selfClosing) {
      stack.push(tok.name)
      scopes.push(local)
    }
  }
  if (stack.length) err(file, `незакрытые теги: ${stack.join(', ')}`)
}

// ---------------------------------------------------------------- модули .js
function jsExports(file) {
  const { sf, diags } = parse(fs.readFileSync(file, 'utf8'), file)
  for (const d of diags) err(file, `синтаксис: ${ts.flattenDiagnosticMessageText(d.messageText, ' ')}`)
  const names = new Set()
  for (const st of sf.statements) {
    const exported = st.modifiers?.some((m) => m.kind === ts.SyntaxKind.ExportKeyword)
    if (!exported) {
      if (ts.isExportAssignment(st)) names.add('default')
      continue
    }
    if (st.modifiers.some((m) => m.kind === ts.SyntaxKind.DefaultKeyword)) names.add('default')
    if (ts.isVariableStatement(st)) st.declarationList.declarations.forEach((d) => bindingNames(d.name, names))
    if ((ts.isFunctionDeclaration(st) || ts.isClassDeclaration(st)) && st.name) names.add(st.name.text)
  }
  return names
}

function walkDir(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) =>
    e.isDirectory() ? walkDir(path.join(dir, e.name)) : [path.join(dir, e.name)])
}

const files = walkDir(ROOT)
const infos = {}
for (const f of files.filter((f) => f.endsWith('.vue'))) {
  const { script, template } = splitSfc(fs.readFileSync(f, 'utf8'))
  if (!script) err(f, 'нет <script setup>')
  if (!template) err(f, 'нет <template>')
  infos[f] = { ...analyzeScript(f, script), template }
}
const exportsCache = {}
for (const f of files.filter((f) => f.endsWith('.js'))) {
  exportsCache[f] = jsExports(f)
  const { sf } = parse(fs.readFileSync(f, 'utf8'), f)
  for (const st of sf.statements.filter(ts.isImportDeclaration)) {
    const from = st.moduleSpecifier.text
    if (!from.startsWith('.')) continue
    const target = path.resolve(path.dirname(f), from)
    if (!fs.existsSync(target)) err(f, `импорт несуществующего файла ${from}`)
  }
}
for (const [f, info] of Object.entries(infos)) {
  const components = {}
  for (const imp of info.imports) {
    if (!imp.from.startsWith('.')) continue
    const target = path.resolve(path.dirname(f), imp.from)
    if (!fs.existsSync(target)) { err(f, `импорт несуществующего файла ${imp.from}`); continue }
    if (target.endsWith('.vue')) {
      if (imp.defaultName) components[imp.defaultName] = infos[target]
    } else {
      const exp = exportsCache[target] || jsExports(target)
      for (const n of imp.named) if (!exp.has(n)) err(f, `«${n}» не экспортируется из ${imp.from}`)
    }
  }
  // рекурсивный компонент по имени файла
  const selfName = path.basename(f, '.vue')
  if (info.template.includes(`<${selfName}`)) {
    info.bindings.add(selfName)
    components[selfName] = info
  }
  analyzeTemplate(f, info.template, info, components)
}
for (const f of files.filter((f) => f.endsWith('.js'))) {
  const { sf } = parse(fs.readFileSync(f, 'utf8'), f)
  for (const st of sf.statements.filter(ts.isImportDeclaration)) {
    const from = st.moduleSpecifier.text
    const c = st.importClause
    if (!from.startsWith('.') || from.endsWith('.vue') || from.endsWith('.css')) continue
    const target = path.resolve(path.dirname(f), from)
    const exp = exportsCache[target]
    if (!exp || !c?.namedBindings || !ts.isNamedImports(c.namedBindings)) continue
    for (const el of c.namedBindings.elements) {
      const n = (el.propertyName || el.name).text
      if (!exp.has(n)) err(f, `«${n}» не экспортируется из ${from}`)
    }
  }
}

const vueCount = Object.keys(infos).length
if (errors.length) {
  console.error(errors.join('\n'))
  console.error(`\nОшибок: ${errors.length} (проверено компонентов: ${vueCount})`)
  process.exit(1)
}
console.log(`SFC OK: ${vueCount} компонентов, ${files.filter((f) => f.endsWith('.js')).length} модулей`)
