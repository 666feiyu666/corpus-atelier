<script setup lang="ts">
const { t, loadTasks } = useAtelier()

onMounted(loadTasks)
</script>

<template>
  <div class="workspace">
    <TaskLedger :current="null" />
    <section class="work-main home-main">
      <StartForm />
    </section>
    <aside class="work-chat home-notes" aria-labelledby="how-heading">
      <h2 id="how-heading">{{ t('howItWorks') }}</h2>
      <ol class="home-steps">
        <li>{{ t('howOne') }}</li>
        <li>{{ t('howTwo') }}</li>
        <li>{{ t('howThree') }}</li>
      </ol>
      <p class="hint">{{ t('tasksHint') }}</p>
    </aside>
  </div>
</template>
