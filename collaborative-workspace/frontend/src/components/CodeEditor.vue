<template>
  <div class="code-editor" ref="editorEl"></div>
</template>

<script setup>
import { ref, watch, onMounted, onBeforeUnmount } from 'vue'
import { EditorView, keymap, placeholder as ph } from '@codemirror/view'
import { EditorState } from '@codemirror/state'
import { python } from '@codemirror/lang-python'
import { oneDark } from '@codemirror/theme-one-dark'
import { defaultKeymap, indentWithTab } from '@codemirror/commands'
import { useWorkspaceStore } from '../stores/workspace'

const store = useWorkspaceStore()
const editorEl = ref(null)
let view = null

function createEditor(content) {
  if (view) {
    view.destroy()
    view = null
  }
  if (!editorEl.value) return

  view = new EditorView({
    state: EditorState.create({
      doc: content,
      extensions: [
        python(),
        oneDark,
        keymap.of([...defaultKeymap, indentWithTab]),
        ph('Open a file to start editing'),
        EditorView.updateListener.of((update) => {
          if (update.docChanged && store.activeTab) {
            store.updateContent(store.activeTab, update.state.doc.toString())
          }
        }),
        EditorView.theme({
          '&': { height: '100%' },
          '.cm-scroller': { overflow: 'auto' },
        }),
      ],
    }),
    parent: editorEl.value,
  })
}

watch(
  () => store.activeTab,
  (tab) => {
    if (tab) {
      createEditor(store.fileContents[tab] ?? '')
    } else {
      createEditor('')
    }
  }
)

onMounted(() => {
  createEditor(store.activeContent ?? '')
})

onBeforeUnmount(() => {
  if (view) view.destroy()
})
</script>
