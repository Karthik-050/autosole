<template>
  <div class="tab-bar">
    <div
      v-for="tab in store.openTabs"
      :key="tab.name"
      class="tab"
      :class="{ active: store.activeTab === tab.name }"
      @click="store.activeTab = tab.name"
    >
      <span class="tab-name">{{ tab.name }}</span>
      <span v-if="tab.modified" class="modified-dot">●</span>
      <button class="tab-close" @click.stop="store.closeTab(tab.name)">×</button>
    </div>
  </div>
</template>

<script setup>
import { useWorkspaceStore } from '../stores/workspace'
const store = useWorkspaceStore()
</script>
