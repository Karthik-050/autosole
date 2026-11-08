<template>
  <div class="app-layout">
    <!-- Notification Banner -->
    <div
      v-if="store.notification"
      class="global-notification"
      :class="store.notification.type"
    >
      <span>{{ store.notification.message }}</span>
      <button class="notif-close" @click="store.notification = null">×</button>
    </div>

    <!-- Persistent Left Navigation Sidebar -->
    <NavigationSidebar />

    <div class="app-content-container">
      <!-- Top Persistent Header -->
      <TopHeader />

      <!-- Main Dynamic Content Views -->
      <main class="main-viewport">
        <DashboardView v-if="store.currentView === 'dashboard'" />
        <WorkspaceView v-else-if="store.currentView === 'workspace'" />
        <GitView v-else-if="store.currentView === 'git'" />
        <AutomatorCICDView v-else-if="store.currentView === 'automator-cicd'" />
        <ValidationView v-else-if="store.currentView === 'validation'" />
        <DockerView v-else-if="store.currentView === 'docker'" />
        <JenkinsView v-else-if="store.currentView === 'jenkins'" />
        <DeploymentsView v-else-if="store.currentView === 'deployments'" />
        <SettingsView v-else-if="store.currentView === 'settings'" />
      </main>
    </div>
  </div>
</template>

<script setup>
import { onMounted } from 'vue'
import { useWorkspaceStore } from './stores/workspace'

import NavigationSidebar from './components/NavigationSidebar.vue'
import TopHeader from './components/TopHeader.vue'

import DashboardView from './views/DashboardView.vue'
import WorkspaceView from './views/WorkspaceView.vue'
import GitView from './views/GitView.vue'
import AutomatorCICDView from './views/AutomatorCICDView.vue'
import ValidationView from './views/ValidationView.vue'
import DockerView from './views/DockerView.vue'
import JenkinsView from './views/JenkinsView.vue'
import DeploymentsView from './views/DeploymentsView.vue'
import SettingsView from './views/SettingsView.vue'

const store = useWorkspaceStore()

onMounted(async () => {
  await store.loadInitialData()

  // Global Ctrl+S handler
  document.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 's') {
      e.preventDefault()
      if (store.currentView === 'workspace' && store.activeTab) {
        store.saveFile(store.activeTab)
      }
    }
  })
})
</script>

<style scoped>
.app-layout {
  display: flex;
  height: 100vh;
  width: 100vw;
  overflow: hidden;
  background: #18181b;
  color: #f4f4f5;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
  position: relative;
}

.app-content-container {
  display: flex;
  flex-direction: column;
  flex: 1;
  overflow: hidden;
}

.main-viewport {
  flex: 1;
  overflow: hidden;
  background: #18181b;
  position: relative;
}

/* Global Notification Banner */
.global-notification {
  position: fixed;
  top: 14px;
  right: 20px;
  padding: 10px 16px;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 500;
  display: flex;
  align-items: center;
  gap: 12px;
  z-index: 1000;
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.4);
  animation: slideIn 0.2s ease-out;
}

@keyframes slideIn {
  from { transform: translateY(-10px); opacity: 0; }
  to { transform: translateY(0); opacity: 1; }
}

.global-notification.success {
  background: #064e3b;
  border: 1px solid #059669;
  color: #34d399;
}

.global-notification.error {
  background: #450a0a;
  border: 1px solid #b91c1c;
  color: #fca5a5;
}

.global-notification.info {
  background: #1e293b;
  border: 1px solid #3b82f6;
  color: #93c5fd;
}

.notif-close {
  background: none;
  border: none;
  color: inherit;
  font-size: 16px;
  cursor: pointer;
  line-height: 1;
}
</style>
