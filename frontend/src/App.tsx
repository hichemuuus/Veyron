import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { Layout } from './components/layout/Layout'
import { ErrorBoundary } from './components/layout/ErrorBoundary'
import { ScrollToTop } from './components/layout/ScrollToTop'
import { DashboardPage } from './pages/Dashboard'
import { AgentWorkspacePage } from './pages/AgentWorkspace'
import { TaskRegistryPage } from './pages/TaskRegistry'
import { TaskDetailPage } from './pages/TaskDetail'
import { ToolCenterPage } from './pages/ToolCenter'
import { ProjectIntelligencePage } from './pages/ProjectIntelligence'
import { MemoryCenterPage } from './pages/MemoryCenter'
import { SystemIntelligencePage } from './pages/SystemIntelligence'
import { LearningDashboardPage } from './pages/LearningDashboard'
import { DiagnosticsPage } from './pages/Diagnostics'
import { SettingsPage } from './pages/Settings'
import { TauriBridge } from './components/tauri/TauriBridge'

export function App() {
  return (
    <ErrorBoundary>
      <BrowserRouter>
        <ScrollToTop />
        <TauriBridge />
        <Routes>
          <Route element={<Layout />}>
            <Route path="/" element={<DashboardPage />} />
            <Route path="/agent" element={<AgentWorkspacePage />} />
            <Route path="/tasks" element={<TaskRegistryPage />} />
            <Route path="/agent/:id" element={<TaskDetailPage />} />
            <Route path="/tools" element={<ToolCenterPage />} />
            <Route path="/projects" element={<ProjectIntelligencePage />} />
            <Route path="/memory" element={<MemoryCenterPage />} />
            <Route path="/system" element={<SystemIntelligencePage />} />
            <Route path="/learning" element={<LearningDashboardPage />} />
            <Route path="/diagnostics" element={<DiagnosticsPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </ErrorBoundary>
  )
}
