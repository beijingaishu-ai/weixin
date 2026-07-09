import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import 'element-plus/dist/index.css'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'

import App from './App.vue'
import router from './router'
import { bindAuthToHttp } from './stores/auth'
import './styles/global.css'

const app = createApp(App)
const pinia = createPinia()

app.use(pinia)

// 注册 http 层的 token 处理 (需在 pinia 之后, router 之前)
bindAuthToHttp()

app.use(router)
app.use(ElementPlus, { locale: zhCn })

// 全量注册 Element Plus 图标
for (const [key, comp] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, comp)
}

app.mount('#app')
