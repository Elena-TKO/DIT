export function projectSummary(buildings = []) {
  const observed = buildings.length > 0 && buildings.every(b => b.photos > 0)
  const average = key => buildings.length && buildings.every(b => Number.isFinite(b[key]))
    ? Math.round(buildings.reduce((sum, b) => sum + b[key], 0) / buildings.length) : null
  const status = buildings.some(b => b.status === 'critical') ? 'critical'
    : buildings.some(b => b.status === 'warning') ? 'warning'
      : observed && buildings.every(b => b.status === 'ok') ? 'ok' : 'unknown'
  return {
    actual: observed ? average('completion_percent') : null,
    planned: average('planned_percent'),
    forecast: observed && buildings.every(b => b.forecast_end && Number.isFinite(Date.parse(b.forecast_end)))
      ? buildings.map(b => b.forecast_end).sort((a, b) => Date.parse(a) - Date.parse(b)).at(-1) : null,
    status,
  }
}
