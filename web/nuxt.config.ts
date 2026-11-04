// The browser interface is a local-first SPA: no Node rendering layer, one
// Python process owns every durable fact. Dev server proxies nothing — the API
// is addressed directly over loopback so the contract stays visible.
export default defineNuxtConfig({
  ssr: false,
  devtools: { enabled: false },
  compatibilityDate: '2025-01-01',
  css: ['~/assets/css/main.css'],
  // 3000/3001 belong to another local project of ours (anti-habit); this
  // interface keeps its own port so neither dev server has to take over.
  devServer: { port: 3210 },
  runtimeConfig: {
    public: {
      // Override with NUXT_PUBLIC_API_BASE when the API is not on the default port.
      apiBase: 'http://127.0.0.1:8787',
    },
  },
  app: {
    head: {
      title: 'Corpus Atelier',
      htmlAttrs: { lang: 'en' },
      meta: [
        { name: 'viewport', content: 'width=device-width, initial-scale=1' },
        { name: 'color-scheme', content: 'light' },
      ],
    },
  },
  typescript: { strict: true },
})
