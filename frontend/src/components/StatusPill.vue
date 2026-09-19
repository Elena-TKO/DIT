<script setup>
import { computed } from 'vue'
import { VERDICT_STATUS } from '../lib/labels.js'

const props = defineProps({
  status: { type: String, default: '' },
  glass: { type: Boolean, default: false },
})
const meta = computed(() => VERDICT_STATUS[props.status] || { label: 'Нет снимков', tone: 'none' })
</script>

<template>
  <span class="status" :class="[meta.tone, { glass }]">{{ meta.label }}</span>
</template>

<style scoped>
.glass { padding: 6px 13px 6px 11px; border-radius: 999px; background: rgba(13, 18, 21, 0.45); border: 1px solid rgba(236, 235, 230, 0.14); backdrop-filter: blur(14px); -webkit-backdrop-filter: blur(14px); }
</style>
