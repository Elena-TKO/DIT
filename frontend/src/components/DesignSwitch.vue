<script setup>
import { DESIGNS, setDesign, ui } from '../store.js'

// Переключатель дизайна: новый светлый ↔ классический тёмный (как до редизайна).
defineProps({ floating: { type: Boolean, default: false } })
</script>

<template>
  <div class="design-switch" :class="{ floating }" role="radiogroup" aria-label="Дизайн интерфейса">
    <span class="design-switch-label">Дизайн</span>
    <button v-for="d in DESIGNS" :key="d.key" type="button" role="radio" :aria-checked="ui.design === d.key"
      :class="{ on: ui.design === d.key }" @click="setDesign(d.key)">{{ d.label }}</button>
  </div>
</template>

<style>
.design-switch { display: flex; align-items: center; gap: 2px; padding: 3px; border: 1px solid var(--hair-2); border-radius: 999px; font-size: 11px; width: fit-content; }
.design-switch-label { padding: 0 8px 0 9px; color: var(--ink-3); }
.design-switch button { font: inherit; border: 0; background: transparent; color: var(--ink-2); padding: 5px 10px; border-radius: 999px; cursor: pointer; }
.design-switch button.on { background: var(--accent); color: var(--accent-ink); font-weight: 600; }
.design-switch.floating { position: fixed; right: 20px; top: 20px; z-index: 50; background: rgba(10, 14, 16, 0.55); border-color: rgba(236, 235, 230, 0.2);
  backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px); }
.design-switch.floating .design-switch-label, .design-switch.floating button:not(.on) { color: rgba(236, 235, 230, 0.8); }
.design-switch.floating button.on { background: #ECEBE6; color: #17130D; }
</style>
