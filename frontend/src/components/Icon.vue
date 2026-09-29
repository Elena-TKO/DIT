<script setup>
defineProps({ name: { type: String, required: true } })
</script>

<template>
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
    <template v-if="name === 'crane'">
      <path d="M6 21V4h1.5l12 3.5H7.5" /><path d="M6 8H3" /><path d="M16 7.5V12" /><path d="M14.5 12h3v2.5h-3z" /><path d="M3 21h7" />
    </template>
    <template v-else-if="name === 'camera'">
      <path d="M4 8h3l1.6-2.4h6.8L17 8h3v11H4z" /><circle cx="12" cy="13" r="3.4" />
    </template>
    <template v-else-if="name === 'upload'">
      <path d="M12 16V4" /><path d="M7 9l5-5 5 5" /><path d="M4 16v4h16v-4" />
    </template>
    <template v-else-if="name === 'plus'">
      <path d="M12 5v14" /><path d="M5 12h14" />
    </template>
    <template v-else-if="name === 'alert'">
      <path d="M12 3.5l9.5 16.5h-19z" /><path d="M12 10v4.2" /><path d="M12 17.2v.1" />
    </template>
    <template v-else-if="name === 'check'">
      <circle cx="12" cy="12" r="9" /><path d="M8 12.3l2.8 2.8L16.2 9.5" />
    </template>
    <template v-else-if="name === 'clock'">
      <circle cx="12" cy="12" r="9" /><path d="M12 7v5l3.2 2" />
    </template>
    <template v-else-if="name === 'report'">
      <path d="M6 3h8.5L19 7.5V21H6z" /><path d="M14 3v5h5" /><path d="M9 13h7" /><path d="M9 17h5" />
    </template>
    <template v-else-if="name === 'logout'">
      <path d="M10 4H5v16h5" /><path d="M15 8l4 4-4 4" /><path d="M19 12H9" />
    </template>
    <template v-else-if="name === 'close'">
      <path d="M6 6l12 12" /><path d="M18 6L6 18" />
    </template>
    <template v-else-if="name === 'play'">
      <path d="M8 5.5v13l10-6.5z" />
    </template>
    <template v-else-if="name === 'pause'">
      <path d="M8.5 5v14" /><path d="M15.5 5v14" />
    </template>
    <template v-else-if="name === 'refresh'">
      <path d="M20 11a8 8 0 1 0-2.3 5.7" /><path d="M20 4.5V11h-6.5" />
    </template>
    <template v-else-if="name === 'pin'">
      <path d="M12 21s-6.5-6.1-6.5-11.2a6.5 6.5 0 0 1 13 0C18.5 14.9 12 21 12 21z" /><circle cx="12" cy="9.8" r="2.3" />
    </template>
    <template v-else-if="name === 'chat'">
      <path d="M4 5h16v11H9l-5 4z" /><path d="M8 9.5h8" /><path d="M8 12.5h5" />
    </template>
    <template v-else-if="name === 'send'">
      <path d="M4 12l16-8-6 16-2.5-6.5z" /><path d="M11.5 13.5L20 4" />
    </template>
    <template v-else-if="name === 'clip'">
      <path d="M20 11.5l-8 8a5 5 0 0 1-7-7l8.5-8.5a3.3 3.3 0 0 1 4.7 4.7l-8.3 8.3a1.7 1.7 0 0 1-2.4-2.4l7.4-7.4" />
    </template>
    <template v-else-if="name === 'stop'">
      <rect x="7" y="7" width="10" height="10" rx="1.5" />
    </template>
    <template v-else-if="name === 'spark'">
      <path d="M12 3l1.9 5.6L19.5 10.5l-5.6 1.9L12 18l-1.9-5.6L4.5 10.5l5.6-1.9z" /><path d="M19 17l.7 1.8 1.8.7-1.8.7L19 22l-.7-1.8-1.8-.7 1.8-.7z" />
    </template>
    <template v-else-if="name === 'image'">
      <rect x="3.5" y="5" width="17" height="14" rx="2" /><circle cx="9" cy="10" r="1.6" /><path d="M20.5 16l-5-5-8.5 8" />
    </template>
    <template v-else>
      <circle cx="12" cy="12" r="8" />
    </template>
  </svg>
</template>
