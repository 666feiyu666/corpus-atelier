<script setup lang="ts">
const { t, loadTasks } = useAtelier()

onMounted(loadTasks)
</script>

<template>
  <div class="workspace home-layout">
    <TaskLedger :current="null" />

    <section class="work-main home-main">
      <header class="home-hero">
        <h1>{{ t('startHeading') }}</h1>
        <p class="home-lead">{{ t('startHint') }}</p>
      </header>

      <StartForm />

      <section class="home-steps" aria-labelledby="how-heading">
        <h2 id="how-heading">{{ t('howItWorks') }}</h2>
        <ol>
          <li>
            <span class="step-index" aria-hidden="true">1</span>
            <span>{{ t('howOne') }}</span>
          </li>
          <li>
            <span class="step-index" aria-hidden="true">2</span>
            <span>{{ t('howTwo') }}</span>
          </li>
          <li>
            <span class="step-index" aria-hidden="true">3</span>
            <span>{{ t('howThree') }}</span>
          </li>
        </ol>
        <p class="hint">{{ t('tasksHint') }}</p>
      </section>
    </section>
  </div>
</template>
