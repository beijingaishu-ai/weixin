<script setup lang="ts">
/**
 * 富文本编辑器组件
 *
 * 优先使用 wangEditor (@wangeditor/editor + @wangeditor/editor-for-vue),
 * 已随 package.json 依赖安装。若后续环境无法安装 wangEditor,
 * 可将下方 USE_WANG_EDITOR 置为 false 走 <textarea> 降级实现,
 * 两种模式对外暴露完全相同的 v-model 接口 (modelValue:string / update:modelValue)。
 *
 * 图片上传: 走后端 POST /materials, 返回本地 url; 插入的 <img> 会带
 * data-material-id 属性, 便于后端/前端追踪素材引用。
 * 也可通过 insertImage() 由父组件 (从素材库选图) 主动插入。
 */
import { computed, onBeforeUnmount, shallowRef } from 'vue'
import '@wangeditor/editor/dist/css/style.css'
import { Editor, Toolbar } from '@wangeditor/editor-for-vue'
import type { IDomEditor, IEditorConfig } from '@wangeditor/editor'
import { apiUploadMaterial } from '@/api/modules'

// 降级开关: 正常使用 wangEditor。若无法联网安装依赖, 置为 false 走 textarea。
const USE_WANG_EDITOR = true

const props = withDefaults(
  defineProps<{
    modelValue?: string
    placeholder?: string
    height?: string
    /** 上传图片时关联的公众号 (可选) */
    mpAccountId?: number
  }>(),
  {
    modelValue: '',
    placeholder: '请输入正文内容...',
    height: '480px',
  },
)

const emit = defineEmits<{
  (e: 'update:modelValue', value: string): void
}>()

// wangEditor 实例 (用 shallowRef, 官方要求)
const editorRef = shallowRef<IDomEditor>()

const valueProxy = computed<string>({
  get: () => props.modelValue || '',
  set: (v) => emit('update:modelValue', v),
})

const toolbarConfig = {}
const editorConfig = computed<Partial<IEditorConfig>>(() => ({
  placeholder: props.placeholder,
  MENU_CONF: {
    // 自定义图片上传: 走 /materials
    uploadImage: {
      async customUpload(file: File, insertFn: (url: string, alt: string, href: string) => void) {
        const mat = await apiUploadMaterial(file, {
          mp_account_id: props.mpAccountId,
          type: 'image',
        })
        // 插入图片; alt/href 留空, data-material-id 在下方 handleCreated 中补充
        insertFn(mat.url, mat.file_name || '', mat.url)
        // 给最近插入的图片打上 data-material-id
        tagLastImage(mat.id)
      },
    },
  },
}))

// 在插入图片后, 给刚插入的 <img> 附加 data-material-id
function tagLastImage(materialId: number) {
  const editor = editorRef.value
  if (!editor) return
  // wangEditor 内部 DOM 更新后再打标记
  window.setTimeout(() => {
    const container = editor.getEditableContainer?.()
    if (!container) return
    const imgs = container.querySelectorAll('img:not([data-material-id])')
    const last = imgs[imgs.length - 1] as HTMLImageElement | undefined
    if (last) last.setAttribute('data-material-id', String(materialId))
  }, 30)
}

function handleCreated(editor: IDomEditor) {
  editorRef.value = editor
}

onBeforeUnmount(() => {
  editorRef.value?.destroy()
  editorRef.value = undefined
})

/**
 * 供父组件调用: 从素材库选图后插入 (带 data-material-id)。
 * 降级模式下追加一段 <img> HTML。
 */
function insertImage(url: string, materialId?: number, alt = '') {
  if (USE_WANG_EDITOR && editorRef.value) {
    editorRef.value.dangerouslyInsertHtml(
      `<img src="${url}" alt="${alt}"${materialId != null ? ` data-material-id="${materialId}"` : ''} />`,
    )
    return
  }
  // 降级: 直接拼到 HTML 末尾
  const tag = `<img src="${url}" alt="${alt}"${
    materialId != null ? ` data-material-id="${materialId}"` : ''
  } />`
  valueProxy.value = `${valueProxy.value}${tag}`
}

defineExpose({ insertImage })
</script>

<template>
  <!-- wangEditor 模式 -->
  <div v-if="USE_WANG_EDITOR" class="rich-editor" :style="{ '--rich-h': height }">
    <Toolbar
      class="rich-toolbar"
      :editor="editorRef"
      :default-config="toolbarConfig"
      mode="default"
    />
    <Editor
      class="rich-body"
      v-model="valueProxy"
      :default-config="editorConfig"
      mode="default"
      @on-created="handleCreated"
    />
  </div>

  <!-- 降级模式: textarea (对外接口一致) -->
  <div v-else class="rich-editor rich-fallback">
    <div class="fallback-tip">
      当前为降级富文本 (纯 HTML 文本域)。可直接编写 HTML 标签。
    </div>
    <textarea
      class="fallback-textarea"
      :style="{ height }"
      :placeholder="placeholder"
      :value="valueProxy"
      @input="valueProxy = ($event.target as HTMLTextAreaElement).value"
    />
  </div>
</template>

<style scoped>
.rich-editor {
  border: 1px solid #dcdfe6;
  border-radius: 4px;
  overflow: hidden;
}
.rich-toolbar {
  border-bottom: 1px solid #dcdfe6;
}
.rich-body {
  height: var(--rich-h, 480px) !important;
  overflow-y: auto;
}
.rich-fallback {
  display: flex;
  flex-direction: column;
}
.fallback-tip {
  padding: 6px 10px;
  font-size: 12px;
  color: #909399;
  background: #f5f7fa;
  border-bottom: 1px solid #ebeef5;
}
.fallback-textarea {
  width: 100%;
  border: none;
  outline: none;
  padding: 10px 12px;
  font-family: 'Consolas', 'Monaco', monospace;
  font-size: 13px;
  line-height: 1.6;
  resize: vertical;
}
</style>
