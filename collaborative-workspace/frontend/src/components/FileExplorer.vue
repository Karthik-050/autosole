<template>
  <div class="file-explorer">
    <div class="panel-header">
      <span>Files</span>
      <div class="header-actions" v-if="store.currentWorkspace">
        <button class="icon-btn" @click="showNewFile = true" title="New file">+</button>
        <button class="icon-btn" @click="store.refreshFiles()" title="Refresh">&#x21bb;</button>
      </div>
    </div>
    <div class="panel-body">
      <div v-if="!store.currentWorkspace" class="empty-state">Select a workspace</div>
      <div v-else-if="!store.files.length" class="empty-state">No files</div>
      <div
        v-for="f in store.files"
        :key="f"
        class="file-item"
        @click="store.openFile(f)"
        @contextmenu.prevent="onContext($event, f)"
      >
        <span class="file-icon">&#x1F4C4;</span>
        <span class="file-name">{{ f }}</span>
      </div>
    </div>
    <div v-if="showNewFile" class="new-file-form">
      <input
        ref="newFileInput"
        v-model="newFileName"
        placeholder="filename.py"
        @keydown.enter="submitNewFile"
        @keydown.esc="showNewFile = false"
        @blur="showNewFile = false"
      />
    </div>
  </div>
</template>

<script setup>
import { ref, watch, nextTick } from 'vue'
import { useWorkspaceStore } from '../stores/workspace'

const store = useWorkspaceStore()
const showNewFile = ref(false)
const newFileName = ref('')
const newFileInput = ref(null)

watch(showNewFile, async (v) => {
  if (v) {
    newFileName.value = ''
    await nextTick()
    newFileInput.value?.focus()
  }
})

async function submitNewFile() {
  const name = newFileName.value.trim()
  if (!name) return
  await store.createFile(name)
  showNewFile.value = false
}

function onContext(e, filename) {
  if (confirm(`Delete ${filename}?`)) {
    store.deleteFile(filename)
  }
}
</script>
