import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { Layout } from './components/layout/Layout'
import { ErrorBoundary } from './components/layout/ErrorBoundary'
import { ScrollToTop } from './components/layout/ScrollToTop'
import { DashboardPage } from './pages/Dashboard'
import { AgentWorkspacePage } from './pages/AgentWorkspace'
import { TaskRegistryPage } from './pages/TaskRegistry'
import { TaskDetailPage } from './pages/TaskDetail'

export function App() {
  return (
    <ErrorBoundary>
      <BrowserRouter>
        <ScrollToTop />
        <Routes>
          <Route element={<Layout />}>
            <Route path="/" element={<DashboardPage />} />
            <Route path="/agent" element={<AgentWorkspacePage />} />
            <Route path="/tasks" element={<TaskRegistryPage />} />
            <Route path="/agent/:id" element={<TaskDetailPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </ErrorBoundary>
  )
}
