<script setup>
import { computed, ref } from 'vue'
import { imageUrl } from '../api.js'
import { formatDateTime } from '../lib/format.js'
import Icon from './Icon.vue'

const props = defineProps({
  ids: { type: Array, required: true },
  photos: { type: Array, default: () => [] },
})
const emit = defineEmits(['close'])

const split = ref(50)
const ordered = computed(() => {
  const found = props.ids.map((id) => props.photos.find((p) => p.id === id)).filter(Boolean)
  return found.sort((a, b) => String(a.taken_at).localeCompare(String(b.taken_at)))
})
const before = computed(() => ordered.value[0])
const after = computed(() => ordered.value[1])
</script>

<template>
  <div class="modal-back" @click.self="emit('close')">
    <div class="compare" role="dialog" aria-modal="true" aria-label="Сравнение кадров">
      <div class="compare-head">
        <div>
          <b>Было — стало</b>
          <span class="faint small" v-if="before && after">
            {{ formatDateTime(before.taken_at) }} → {{ formatDateTime(after.taken_at) }}
          </span>
        </div>
        <button class="btn small glass" type="button" aria-label="Закрыть" @click="emit('close')"><Icon name="close" /></button>
      </div>
      <div v-if="before && after" class="viewer">
        <img class="base" :src="imageUrl(after.id, 1600)" alt="Кадр «стало»" />
        <div class="overlay" :style="{ width: split + '%' }">
          <img :src="imageUrl(before.id, 1600)" alt="Кадр «было»" />
        </div>
        <span class="handle" :style="{ left: split + '%' }" aria-hidden="true"></span>
        <span class="mark left">было</span>
        <span class="mark right">стало</span>
      </div>
      <label class="slider">
        <span class="sr">Положение шторки сравнения</span>
        <input v-model.number="split" type="range" min="0" max="100" />
      </label>
    </div>
  </div>
</template>

<style scoped>
.compare { width: min(1200px, 100%); background: #070A0B; border: 1px solid var(--hair); border-radius: var(--r-xl); padding: 20px 24px 24px; }
.compare-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; gap: 16px; }
.compare-head b { font-family: var(--serif); font-size: 22px; font-weight: 500; margin-right: 12px; }
.viewer { position: relative; line-height: 0; border-radius: var(--r-m); overflow: hidden; }
.viewer img { width: 100%; display: block; }
.overlay { position: absolute; inset: 0 auto 0 0; overflow: hidden; }
.overlay img { position: absolute; inset: 0; width: auto; height: 100%; max-width: none; }
.handle { position: absolute; top: 0; bottom: 0; width: 2px; background: var(--accent); transform: translateX(-1px); }
.mark { position: absolute; bottom: 14px; padding: 4px 11px; border-radius: 999px; background: rgba(10, 14, 16, 0.6);
  border: 1px solid rgba(236, 235, 230, 0.14); backdrop-filter: blur(8px); font-size: 12px; line-height: 1.4; }
.mark.left { left: 14px; }
.mark.right { right: 14px; }
.slider { display: block; margin-top: 16px; }
.slider input { width: 100%; accent-color: var(--accent); padding: 0; background: none; border: 0; }
</style>
