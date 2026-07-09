/**
 * 类型补丁: @wangeditor/editor-for-vue 的 package.json "exports" 未声明 types 字段,
 * 在 moduleResolution=bundler 下 vue-tsc 无法解析其自带的 dist/src/index.d.ts。
 * 这里手动把两个组件声明为 Vue 组件, 消除隐式 any。
 */
declare module '@wangeditor/editor-for-vue' {
  import type { DefineComponent } from 'vue'
  export const Editor: DefineComponent<Record<string, unknown>>
  export const Toolbar: DefineComponent<Record<string, unknown>>
}
