<script setup lang="ts">
const { t, notice, reachable, settings, loadSettings, loadTasks } = useAtelier()
const showSettings = ref(false)

const credentialLabel = computed(() => {
  const credential = settings.value?.credential
  if (!credential?.configured) return t('apiMissing')
  return t('apiConfigured', { masked: credential.masked ?? '' })
})

onMounted(async () => {
  await loadSettings()
  await loadTasks()
})
</script>

<template>
  <div class="shell">
    <header class="masthead">
      <NuxtLink to="/" class="brand">
        <span class="wordmark">Corpus <span>Atelier</span></span>
        <span class="brand-sub">{{ t('tagline') }}</span>
      </NuxtLink>
      <nav aria-label="Primary">
        <NuxtLink to="/">{{ t('navStudio') }}</NuxtLink>
        <NuxtLink to="/gallery">{{ t('navGallery') }}</NuxtLink>
        <button type="button" class="nav-quiet" @click="showSettings = true">
          {{ t('navSettings') }}
        </button>
        <span v-if="settings" class="who">{{ credentialLabel }}</span>
      </nav>
    </header>

    <main>
      <div v-if="!reachable" class="notice" data-tone="warn" style="margin: 18px 22px">
        {{ t('apiDown') }}
      </div>
      <NuxtPage />
    </main>

    <SettingsDialog v-if="showSettings" @close="showSettings = false" />
    <p v-if="notice" class="toast" :data-tone="notice.tone">{{ notice.text }}</p>
  </div>
</template>
