<script setup>
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api.js'
import { formatDate, formatDateTime } from '../lib/format.js'

const route = useRoute()
const router = useRouter()

const loading = ref(true)
const error = ref('')

const phase = ref(null)
const photos = ref([])

const buildingId = route.params.buildingId
const phaseId = route.params.phaseId

async function load() {
  loading.value = true
  error.value = ''

  try {
    /*
     * Здесь запрос информации об этапе.
     *
     * Например:
     * GET /api/buildings/{buildingId}/phases/{phaseId}
     */
    phase.value = await api.phase(buildingId, phaseId)

    /*
     * Здесь запрос фотографий этапа.
     *
     * Например:
     * GET /api/buildings/{buildingId}/phases/{phaseId}/photos
     */
    photos.value = await api.phasePhotos(buildingId, phaseId)
  } catch (e) {
    error.value = e.message || 'Не удалось загрузить этап'
  } finally {
    loading.value = false
  }
}

function goBack() {
  router.back()
}

onMounted(load)
</script>

<template>
  <section class="stack">
    <!-- Загрузка -->
    <div v-if="loading" class="panel loading">
      <p>Загрузка этапа…</p>
    </div>

    <!-- Ошибка -->
    <div v-else-if="error" class="panel">
      <p class="error" role="alert">{{ error }}</p>

      <button class="btn" type="button" @click="load">
        Повторить
      </button>
    </div>

    <!-- Этап -->
    <template v-else-if="phase">
      <div class="panel">
        <div class="panel-head">
          <div>
            <button
              class="back"
              type="button"
              @click="goBack"
            >
              ← Назад
            </button>

            <h1>{{ phase.name }}</h1>

            <p v-if="phase.description" class="muted">
              {{ phase.description }}
            </p>
          </div>
        </div>

        <!-- Основная информация -->
        <div class="phase-info">
          <div class="info-item">
            <span class="info-label">Начало</span>
            <b>{{ formatDate(phase.start) }}</b>
          </div>

          <div class="info-item">
            <span class="info-label">Окончание</span>
            <b>{{ formatDate(phase.end) }}</b>
          </div>

          <div class="info-item">
            <span class="info-label">Статус</span>
            <b>{{ phase.status_label || phase.status || '—' }}</b>
          </div>

          <div class="info-item">
            <span class="info-label">Последнее обновление</span>
            <b>
              {{ phase.updated_at ? formatDateTime(phase.updated_at) : '—' }}
            </b>
          </div>
        </div>
      </div>

      <!-- Фотографии -->
      <div class="panel">
        <div class="section-head">
          <div>
            <h2>Фотографии этапа</h2>
            <p class="muted small">
              Фотографии, относящиеся к выбранному этапу.
            </p>
          </div>

          <span class="photo-count">
            {{ photos.length }}
          </span>
        </div>

        <div v-if="!photos.length" class="empty">
          <p>Для этого этапа фотографий пока нет.</p>
        </div>

        <div v-else class="photos">
          <article
            v-for="photo in photos"
            :key="photo.id"
            class="photo-card"
          >
            <img
              :src="photo.url"
              :alt="photo.caption || `Фото этапа ${phase.name}`"
              loading="lazy"
            />

            <div class="photo-meta">
              <span v-if="photo.date">
                {{ formatDate(photo.date) }}
              </span>

              <span v-if="photo.caption">
                {{ photo.caption }}
              </span>
            </div>
          </article>
        </div>
      </div>
    </template>
  </section>
</template>

<style scoped>
.loading {
  padding: 40px;
  text-align: center;
}

.back {
  border: 0;
  padding: 0;
  margin-bottom: 18px;
  background: transparent;
  color: var(--ink-3);
  cursor: pointer;
  font: inherit;
}

.back:hover {
  color: var(--accent);
}

.panel-head h1 {
  margin: 0;
}

.phase-info {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 18px;
  margin-top: 28px;
  padding-top: 22px;
  border-top: 1px solid var(--hair);
}

.info-item {
  display: grid;
  gap: 6px;
}

.info-label {
  font-size: 12px;
  color: var(--ink-3);
}

.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  margin-bottom: 22px;
}

.section-head h2 {
  margin: 0 0 5px;
}

.photo-count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 32px;
  height: 32px;
  padding: 0 10px;
  border-radius: 999px;
  background: var(--hair);
}

.photos {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 18px;
}

.photo-card {
  overflow: hidden;
  border: 1px solid var(--hair);
  border-radius: 10px;
  background: var(--night);
}

.photo-card img {
  display: block;
  width: 100%;
  aspect-ratio: 4 / 3;
  object-fit: cover;
}

.photo-meta {
  display: flex;
  flex-direction: column;
  gap: 5px;
  padding: 12px;
  font-size: 12px;
  color: var(--ink-3);
}

@media (max-width: 900px) {
  .phase-info {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .photos {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 600px) {
  .phase-info {
    grid-template-columns: 1fr;
  }

  .photos {
    grid-template-columns: 1fr;
  }
}
</style>