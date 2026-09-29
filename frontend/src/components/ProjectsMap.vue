<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import * as L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { api, imageUrl, reportUrl } from '../api.js'
import { ui } from '../store.js'
import { formatDate } from '../lib/format.js'
import { MAP_STATUS, MOSCOW, popupHtml, statusColor } from '../lib/map.js'
import Icon from './Icon.vue'

// Карта строек Москвы. Точки берутся из координат стройки; у кого их нет — бэкенд геокодирует адрес
// (Яндекс → OpenStreetMap → справочник округов). Если адрес не распознан, точку можно поставить вручную.
const props = defineProps({
  projects: { type: Array, default: () => [] },
  summaries: { type: Object, default: () => ({}) },
})

const TILES = import.meta.env.VITE_MAP_TILES || 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'
const ATTRIBUTION = import.meta.env.VITE_MAP_ATTRIBUTION || '&copy; участники OpenStreetMap'

const router = useRouter()
const el = ref(null)
const coords = ref({})          // id → { lat, lon, geo_source }
const pending = ref(0)          // сколько адресов ещё геокодируется
const tried = ref(new Set())
const placing = ref(null)       // стройка, для которой ставим точку вручную
const error = ref('')
let map = null
let layer = null
let fitted = false
const markers = new Map()

const legend = Object.entries(MAP_STATUS).map(([key, v]) => ({ key, ...v }))
const point = (p) => coords.value[p.id] || (p.lat != null && p.lon != null ? { lat: p.lat, lon: p.lon, geo_source: p.geo_source } : null)
const placed = computed(() => props.projects.filter((p) => point(p)))
const unplaced = computed(() => props.projects.filter((p) => !point(p) && tried.value.has(p.id)))

function render() {
  if (!map) return
  // пересборка меток не должна закрывать карточку, которую пользователь сейчас смотрит
  const openId = [...markers].find(([, m]) => m.isPopupOpen())?.[0]
  layer.clearLayers()
  markers.clear()
  for (const p of placed.value) {
    const c = point(p)
    const summary = props.summaries[p.id]
    const status = summary?.error ? 'unknown' : summary?.status || 'unknown'
    const marker = L.circleMarker([c.lat, c.lon], {
      radius: 10, weight: 3, color: ui.design === 'classic' ? '#0D1215' : '#ffffff', fillColor: statusColor(status), fillOpacity: 0.95,
      dashArray: c.geo_source === 'approx' ? '4 3' : null,
    })
    marker.bindTooltip(p.name, { direction: 'top', offset: [0, -8] })
    marker.bindPopup(() => popupHtml({ ...p, geo_source: c.geo_source }, summary && !summary.error ? summary : null, {
      coverUrl: p.cover_photo_id ? imageUrl(p.cover_photo_id, 480) : '',
      reportHref: reportUrl(p.id),
      forecast: summary?.forecast ? formatDate(summary.forecast) : '',
    }), { maxWidth: 300, minWidth: 240 })
    marker.addTo(layer)
    markers.set(p.id, marker)
  }
  if (openId !== undefined) markers.get(openId)?.openPopup()
  if (!fitted && placed.value.length) {
    const bounds = L.latLngBounds(placed.value.map((p) => [point(p).lat, point(p).lon]))
    map.fitBounds(bounds.pad(0.3), { maxZoom: 13 })
    fitted = true
  }
}

async function geocodeMissing() {
  const queue = props.projects.filter((p) => !point(p) && !tried.value.has(p.id))
  pending.value += queue.length
  for (const p of queue) {
    try {
      const res = await api.geocodeProject(p.id)
      if (res.found) coords.value = { ...coords.value, [p.id]: { lat: res.lat, lon: res.lon, geo_source: res.geo_source } }
    } catch {
      // адрес не распознан или сеть недоступна — стройка попадёт в список «не на карте»
    } finally {
      tried.value = new Set([...tried.value, p.id])
      pending.value -= 1
      render()
    }
  }
}

function startPlacing(p) {
  placing.value = p
  error.value = ''
  map?.getContainer().classList.add('placing')
  el.value?.scrollIntoView({ behavior: 'smooth', block: 'center' })
}

function cancelPlacing() {
  placing.value = null
  map?.getContainer().classList.remove('placing')
}

async function onMapClick(event) {
  if (!placing.value) return
  const p = placing.value
  cancelPlacing()
  try {
    const res = await api.placeProject(p.id, event.latlng.lat, event.latlng.lng)
    coords.value = { ...coords.value, [p.id]: { lat: res.lat, lon: res.lon, geo_source: res.geo_source } }
    render()
    markers.get(p.id)?.openPopup()
  } catch (e) {
    error.value = e.message
  }
}

function onPopupOpen(event) {
  const button = event.popup.getElement()?.querySelector('[data-open]')
  if (button) button.addEventListener('click', () => router.push(`/projects/${button.dataset.open}`), { once: true })
}

function focusProject(p) {
  const marker = markers.get(p.id)
  if (!marker || !map) return
  map.setView(marker.getLatLng(), Math.max(map.getZoom(), 13))
  marker.openPopup()
}

onMounted(() => {
  map = L.map(el.value, { scrollWheelZoom: false, zoomSnap: 0.5 }).setView(MOSCOW, 10)
  L.tileLayer(TILES, { maxZoom: 19, attribution: ATTRIBUTION }).addTo(map)
  layer = L.layerGroup().addTo(map)
  map.on('click', onMapClick)
  map.on('popupopen', onPopupOpen)
  // колесо мыши масштабирует карту только после клика по ней — иначе мешает прокрутке страницы
  map.on('focus click', () => map.scrollWheelZoom.enable())
  map.on('blur mouseout', () => map.scrollWheelZoom.disable())
  render()
  geocodeMissing()
})

watch(() => props.projects, () => { render(); geocodeMissing() })
watch(() => props.summaries, render, { deep: true })

onBeforeUnmount(() => {
  map?.remove()
  map = null
})

defineExpose({ focusProject })
</script>

<template>
  <section class="map-section" aria-labelledby="map-title">
    <header class="map-heading">
      <div>
        <h2 id="map-title">Карта строек</h2>
        <p>Москва · {{ placed.length }} из {{ projects.length }} на карте<template v-if="pending"> · определяем адреса…</template></p>
      </div>
      <ul class="map-legend">
        <li v-for="s in legend" :key="s.key"><i :style="{ background: s.color }"></i>{{ s.label }}</li>
      </ul>
    </header>
    <div class="map-frame">
      <div ref="el" class="map-canvas" role="application" aria-label="Карта строек Москвы"></div>
      <div v-if="placing" class="map-hint" role="status">
        <Icon name="pin" />Кликните по карте, чтобы поставить «{{ placing.name }}»
        <button type="button" @click="cancelPlacing">Отмена</button>
      </div>
    </div>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <div v-if="unplaced.length" class="map-unplaced">
      <span>Адрес не найден на карте:</span>
      <button v-for="p in unplaced" :key="p.id" type="button" @click="startPlacing(p)"><Icon name="pin" />{{ p.name }} — указать</button>
    </div>
    <div v-if="placed.length > 1" class="map-quick">
      <button v-for="p in placed" :key="p.id" type="button" @click="focusProject(p)">
        <i :style="{ background: statusColor(summaries[p.id]?.status) }"></i>{{ p.name }}
      </button>
    </div>
  </section>
</template>

<style>
/* Цвета через переменные: светлый дизайн по умолчанию, классический тёмный — в .design-classic */
.map-section, .leaflet-popup { --mp-surface:#fff; --mp-surface-2:#f6f8fb; --mp-line:#dde5ec; --mp-ink:#1f2430; --mp-muted:#7b8596; --mp-accent:#3568f2; --mp-accent-soft:#edf2ff; --mp-violet:#6f63ff; --mp-violet-soft:#f0ebff; --mp-danger:#b42336; --mp-on-accent:#fff; --mp-focus:#4073f41a; --mp-serif:Georgia, serif; --mp-sans:Inter, "Segoe UI", sans-serif; }
.design-classic :is(.map-section, .leaflet-popup) { --mp-surface:var(--panel); --mp-surface-2:var(--panel-2); --mp-line:var(--hair-2); --mp-ink:var(--ink); --mp-muted:var(--ink-3); --mp-accent:var(--accent); --mp-accent-soft:var(--accent-soft); --mp-violet:var(--accent-2); --mp-violet-soft:var(--accent-soft); --mp-danger:var(--critical); --mp-on-accent:var(--accent-ink); --mp-focus:rgba(205, 183, 143, 0.15); --mp-serif:var(--serif); --mp-sans:var(--font); }
.design-classic .map-section .leaflet-tile-pane { filter: invert(1) hue-rotate(180deg) brightness(0.85) contrast(0.9) saturate(0.6); }
.design-classic .leaflet-popup-content-wrapper, .design-classic .leaflet-popup-tip { background: var(--panel); color: var(--ink); box-shadow: var(--shadow); }
.design-classic .leaflet-container { background: var(--panel-2); }
.design-classic .leaflet-bar a { background: var(--panel); color: var(--ink); border-color: var(--hair-2); }
.design-classic .leaflet-control-attribution { background: rgba(10, 14, 16, 0.7); color: var(--ink-3); }
.design-classic .leaflet-control-attribution a { color: var(--accent); }
.design-classic .map-hint { background: var(--accent); color: var(--accent-ink); }
.design-classic .map-hint button { color: var(--accent-ink); text-decoration: underline; }
.design-classic .map-heading h2 { font-weight: 500; font-size: 40px; }
.map-section { margin-top:48px; }
.map-heading { display:flex; justify-content:space-between; align-items:flex-end; gap:24px; flex-wrap:wrap; margin-bottom:18px; }
.map-heading h2 { font:400 34px/40px var(--mp-serif); }
.map-heading p { margin:8px 0 0; color:var(--mp-muted); font-size:13px; }
.map-legend { list-style:none; display:flex; flex-wrap:wrap; gap:16px; margin:0; padding:0; font-size:12px; color:var(--mp-muted); }
.map-legend li { display:flex; align-items:center; gap:6px; }
.map-legend i, .map-quick i { width:10px; height:10px; border-radius:50%; display:inline-block; }
.map-frame { position:relative; isolation:isolate; border-radius:22px; overflow:hidden; background:var(--mp-surface-2); border:1px solid var(--mp-line); }
.map-canvas { height:480px; width:100%; }
.map-canvas.placing, .map-canvas.placing .leaflet-interactive { cursor:crosshair !important; }
.map-hint { position:absolute; top:16px; left:50%; transform:translateX(-50%); z-index:1000; display:flex; align-items:center; gap:10px; background:var(--mp-ink); color:var(--mp-on-accent); padding:10px 16px; border-radius:999px; font-size:13px; box-shadow:0 8px 24px #15203340; white-space:nowrap; }
.map-hint svg { width:16px; height:16px; }
.map-hint button { background:none; border:0; color:#9fb8ff; font:inherit; cursor:pointer; }
.map-unplaced, .map-quick { display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin-top:14px; font-size:12px; color:var(--mp-muted); }
.map-unplaced button, .map-quick button { display:inline-flex; align-items:center; gap:6px; border:1px solid var(--mp-line); background:var(--mp-surface); border-radius:999px; padding:6px 12px; font:inherit; color:var(--mp-ink); cursor:pointer; }
.map-unplaced button:hover, .map-quick button:hover { border-color:var(--mp-accent); color:var(--mp-accent); }
.map-unplaced svg { width:13px; height:13px; }
.map-pop { display:grid; gap:4px; font-family:var(--mp-sans); }
.map-pop-cover { width:100%; aspect-ratio:16/9; object-fit:cover; border-radius:8px; margin-bottom:6px; background:var(--mp-surface-2); }
.map-pop-status { font-size:11px; font-weight:700; }
.map-pop-title { font:400 20px/1.2 var(--mp-serif); color:var(--mp-ink); }
.map-pop-address, .map-pop-geo { font-size:12px; color:var(--mp-muted); }
.map-pop-facts { font-size:12px; color:var(--mp-ink); }
.map-pop-actions { display:flex; gap:12px; align-items:center; margin-top:8px; }
.map-pop-actions button { background:var(--mp-accent); color:var(--mp-on-accent); border:0; border-radius:8px; padding:7px 12px; font:inherit; font-size:12px; font-weight:700; cursor:pointer; }
.map-pop-actions a { font-size:12px; color:var(--mp-accent); }
.leaflet-container { font-family:var(--mp-sans); }
@media(max-width:760px) { .map-canvas { height:360px; } .map-heading h2 { font-size:28px; } }
</style>
