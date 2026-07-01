import './index.css'

import { createApp } from 'vue'
import router from './router'
import App from './App.vue'
import { createPinia } from 'pinia'
// import '../polyfills'

import {
  Button,
  Card,
  Input,
  setConfig,
  frappeRequest,
  resourcesPlugin,
} from 'frappe-ui'

// create a pinia instance
let pinia = createPinia()

let app = createApp(App)

setConfig('resourceFetcher', frappeRequest)

app.use(pinia)
app.use(router)
app.use(resourcesPlugin)

app.component('Button', Button)
app.component('Card', Card)
app.component('Input', Input)

// Mount regardless of whether the initial navigation resolved. If the first
// route's lazy chunk fails to load (e.g. a stale index.html after a deploy),
// router.onError triggers a one-time reload; without this .catch/.finally the
// app would never mount and the user would be stuck on a blank page.
router.isReady()
  .catch(() => {})
  .finally(() => {
    app.mount('#app')
  })
