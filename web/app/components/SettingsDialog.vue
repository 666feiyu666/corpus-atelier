<script setup lang="ts">
const emit = defineEmits<{ close: [] }>()

const { t, settings, setLanguage, saveCredential, clearCredential, testCredential } =
  useAtelier()

const apiKey = ref('')
const remember = ref(true)
const busy = ref(false)
const testResult = ref<boolean | null>(null)

const languages = computed(() => settings.value?.languages ?? [])
const credential = computed(() => settings.value?.credential)

async function onSave(): Promise<void> {
  if (!apiKey.value.trim()) return
  busy.value = true
  try {
    await saveCredential(apiKey.value.trim(), remember.value)
    apiKey.value = ''
    testResult.value = null
  } finally {
    busy.value = false
  }
}

async function onTest(): Promise<void> {
  busy.value = true
  try {
    testResult.value = await testCredential(apiKey.value.trim())
  } finally {
    busy.value = false
  }
}

async function onClear(): Promise<void> {
  busy.value = true
  try {
    await clearCredential()
    apiKey.value = ''
    testResult.value = null
  } finally {
    busy.value = false
  }
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape') emit('close')
}
</script>

<template>
  <div class="scrim" @click.self="emit('close')" @keydown="onKeydown">
    <section class="dialog" role="dialog" aria-modal="true" aria-labelledby="settings-heading">
      <header class="row" style="justify-content: space-between">
        <h2 id="settings-heading">{{ t('settingsHeading') }}</h2>
        <button type="button" class="btn-quiet" @click="emit('close')">{{ t('close') }}</button>
      </header>

      <hr class="rule" />

      <div class="stack">
        <div>
          <label class="field" for="settings-language">{{ t('interfaceLanguage') }}</label>
          <select
            id="settings-language"
            :value="settings?.language"
            @change="setLanguage(($event.target as HTMLSelectElement).value)"
          >
            <option v-for="item in languages" :key="item.id" :value="item.id">
              {{ item.label }}
            </option>
          </select>
        </div>

        <div>
          <h3>{{ t('apiSection') }}</h3>
          <p class="dim" style="font-size: 13px; margin-top: 4px">
            {{
              credential?.configured
                ? t('apiConfigured', { masked: credential.masked ?? '' })
                : t('apiMissing')
            }}
          </p>

          <form class="stack" style="margin-top: 10px" @submit.prevent="onSave">
            <div>
              <label class="field" for="settings-key">{{ t('apiKey') }}</label>
              <input
                id="settings-key"
                v-model="apiKey"
                type="password"
                autocomplete="off"
                :placeholder="t('apiKeyPlaceholder')"
              />
            </div>
            <label class="row" style="font-size: 13.5px">
              <input v-model="remember" type="checkbox" />
              <span>{{ t('rememberKey') }}</span>
            </label>
            <div class="row">
              <button class="btn btn-primary" type="submit" :disabled="busy || !apiKey.trim()">
                {{ t('saveKey') }}
              </button>
              <button class="btn" type="button" :disabled="busy" @click="onTest">
                {{ t('testConnection') }}
              </button>
              <button
                v-if="credential?.configured"
                class="btn-danger"
                type="button"
                :disabled="busy"
                @click="onClear"
              >
                {{ t('clearKey') }}
              </button>
            </div>
          </form>
          <p v-if="testResult === true" class="notice" style="margin-top: 10px">
            {{ t('testOk') }}
          </p>
          <p v-else-if="testResult === false" class="notice" data-tone="warn">
            {{ t('testFail') }}
          </p>
        </div>
      </div>
    </section>
  </div>
</template>
