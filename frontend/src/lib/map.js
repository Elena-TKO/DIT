// Чистые функции карты строек: цвет метки, подписи и HTML всплывающей карточки (без зависимостей от Leaflet).

export const MOSCOW = [55.7558, 37.6173]

export const MAP_STATUS = {
  ok: { label: 'Всё по плану', color: '#248550' },
  warning: { label: 'Есть отклонения', color: '#6f63ff' },
  critical: { label: 'Критические отклонения', color: '#b42336' },
  unknown: { label: 'Недостаточно данных', color: '#8a94a6' },
}

export const GEO_SOURCE = {
  yandex: 'по адресу',
  nominatim: 'по адресу',
  approx: 'приблизительно — по округу или магистрали',
  manual: 'указано вручную',
}

export function statusColor(status) {
  return (MAP_STATUS[status] || MAP_STATUS.unknown).color
}

export function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c])
}

const pct = (v) => (v === null || v === undefined ? '—' : `${v}%`)

/**
 * HTML карточки стройки во всплывающем окне карты. Все пользовательские строки экранируются.
 * Кнопка «Открыть» помечена data-open — компонент карты перехватывает клик и переходит роутером.
 */
export function popupHtml(project, summary, { coverUrl = '', reportHref = '', forecast = '' } = {}) {
  const status = summary?.status || 'unknown'
  const s = MAP_STATUS[status] || MAP_STATUS.unknown
  const geo = GEO_SOURCE[project.geo_source] ? `<span class="map-pop-geo">Точка: ${escapeHtml(GEO_SOURCE[project.geo_source])}</span>` : ''
  return `<div class="map-pop">`
    + (coverUrl ? `<img class="map-pop-cover" src="${escapeHtml(coverUrl)}" alt="" />` : '')
    + `<span class="map-pop-status" style="color:${s.color}">${escapeHtml(summary ? s.label : 'Загрузка показателей…')}</span>`
    + `<b class="map-pop-title">${escapeHtml(project.name)}</b>`
    + `<span class="map-pop-address">${escapeHtml(project.address || 'Адрес не указан')}</span>`
    + `<span class="map-pop-facts">Готовность <b>${pct(summary?.actual)}</b> · план ${pct(summary?.planned)}`
    + ` · объектов ${project.buildings_count ?? '—'} · камер ${project.cameras_count ?? '—'}</span>`
    + (forecast ? `<span class="map-pop-facts">Прогноз окончания: ${escapeHtml(forecast)}</span>` : '')
    + geo
    + `<span class="map-pop-actions"><button type="button" data-open="${Number(project.id)}">Открыть стройку</button>`
    + (reportHref ? `<a href="${escapeHtml(reportHref)}" target="_blank" rel="noopener">Отчёт</a>` : '')
    + `</span></div>`
}
