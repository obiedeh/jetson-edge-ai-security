import { NavLink, Route, BrowserRouter as Router, Routes, Navigate } from 'react-router-dom'
import AlertsPage from './pages/Alerts'
import ArtifactsPage from './pages/Artifacts'
import LookbackPage from './pages/Lookback'
import ModelHealthPage from './pages/ModelHealth'
import SettingsPage from './pages/Settings'

const NAV_ITEMS = [
  { to: '/alerts', label: 'Live Alerts', icon: '⚡' },
  { to: '/lookback', label: 'Lookback', icon: '📊' },
  { to: '/model-health', label: 'Model Health', icon: '🔬' },
  { to: '/artifacts', label: 'Artifacts', icon: '📁' },
  { to: '/settings', label: 'Settings', icon: '⚙' },
]

function cn(...cls: (string | undefined | false)[]) {
  return cls.filter(Boolean).join(' ')
}

export default function App() {
  return (
    <Router>
      <div style={{ display: 'flex', minHeight: '100vh' }}>
        <nav className="sidebar">
          <div className="sidebar-logo">
            <div style={{ fontSize: '14px', fontWeight: 700, color: '#fff', letterSpacing: '0.05em' }}>Edge IDS</div>
            <div style={{ fontSize: '11px', color: '#6b7280', marginTop: '2px' }}>Intrusion Detection System</div>
          </div>
          <div className="sidebar-nav">
            {NAV_ITEMS.map(({ to, label, icon }) => (
              <NavLink
                key={to}
                to={to}
                className={({ isActive }) => cn('nav-link', isActive ? 'nav-link-active' : undefined)}
              >
                <span style={{ fontSize: '16px' }}>{icon}</span>
                {label}
              </NavLink>
            ))}
          </div>
          <div className="sidebar-footer">v0.1.0 · Commit 3</div>
        </nav>
        <main className="main-content">
          <div className="content-inner">
            <Routes>
              <Route path="/" element={<Navigate to="/alerts" replace />} />
              <Route path="/alerts" element={<AlertsPage />} />
              <Route path="/lookback" element={<LookbackPage />} />
              <Route path="/model-health" element={<ModelHealthPage />} />
              <Route path="/artifacts" element={<ArtifactsPage />} />
              <Route path="/settings" element={<SettingsPage />} />
            </Routes>
          </div>
        </main>
      </div>
    </Router>
  )
}
