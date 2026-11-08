<template>
  <div class="workspace-view">
    <div class="workspace-sidebar">
      <WorkspaceList />
      <FileExplorer />
    </div>

    <div class="workspace-main">
      <TabBar />
      <div class="editor-area">
        <CodeEditor />
      </div>
      <OutputPanel />
    </div>
  </div>
</template>

<script setup>
import WorkspaceList from '../components/WorkspaceList.vue'
import FileExplorer from '../components/FileExplorer.vue'
import TabBar from '../components/TabBar.vue'
import CodeEditor from '../components/CodeEditor.vue'
import OutputPanel from '../components/OutputPanel.vue'
</script>

<style scoped>
.workspace-view {
  display: flex;
  flex: 1;
  height: 100%;
  overflow: hidden;
}

.workspace-sidebar {
  width: 220px;
  min-width: 180px;
  display: flex;
  flex-direction: column;
  border-right: 1px solid #333;
  background: #252526;
  flex-shrink: 0;
}

.workspace-main {
  display: flex;
  flex-direction: column;
  flex: 1;
  overflow: hidden;
  background: #1e1e1e;
}

.editor-area {
  flex: 1;
  overflow: hidden;
}
</style>
