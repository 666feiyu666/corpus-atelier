<script setup lang="ts">
import { statusText, statusTone } from '~/i18n'

const props = defineProps<{ status: string; running?: boolean }>()
const { locale } = useAtelier()

const tone = computed(() => statusTone(props.status))
const label = computed(() =>
  props.running ? `${statusText(locale.value, props.status)} …` : statusText(locale.value, props.status),
)
</script>

<template>
  <span class="status" :data-tone="tone">{{ label }}</span>
</template>
