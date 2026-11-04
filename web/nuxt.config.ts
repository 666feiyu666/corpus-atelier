// The browser interface is a local-first SPA: no Node rendering layer, one
// Python process owns every durable fact. Dev server proxies nothing — the API
// is addressed directly over loopback so the contract stays visible.
export default defineNuxtConfig({
  ssr: false,
  devtools: { enabled: false },
  compatibilityDate: '2025-01-01',
  css: ['~/assets/css/main.css'],
  // Two profiles, two ports. Daily use is `npm run preview` on 3212 against the
  // daily API (8789); development is `npm run dev` on 3213 against a separate
  // API process (`corpus-atelier api --dev`, 8790) with its own data root.
  // 3000/3001 additionally belong to another local project (anti-habit), and
  // 3210/3211 plus API 8787/8788 were used by another project before this one.
  devServer: { port: 3213 },
  runtimeConfig: {
    public: {
      // Empty means "same origin": daily use is one Python process serving both
      // the API and the built SPA. The dev script overrides this with :8790.
      apiBase: '',
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
