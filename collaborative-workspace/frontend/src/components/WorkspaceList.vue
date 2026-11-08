<template>
  <div class="workspace-list">
    <div class="panel-header">
      <span>Workspaces</span>
      <button class="icon-btn" @click="store.createWorkspace()" title="New workspace">+</button>
    </div>
    <div class="panel-body">
      <div v-if="!store.workspaces.length" class="empty-state">No workspaces</div>
      <div
        v-for="ws in store.workspaces"
        :key="ws"
        class="workspace-item"
        :class="{ active: store.currentWorkspace === ws }"
        @click="store.selectWorkspace(ws)"
      >
        <span class="ws-name" :title="ws">{{ shortId(ws) }}</span>
        <button class="icon-btn danger" @click.stop="store.deleteWorkspace(ws)" title="Delete">×</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { useWorkspaceStore } from '../stores/workspace'
const store = useWorkspaceStore()

function shortId(id) {
  return id.slice(0, 8)
}
</script>
