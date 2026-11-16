import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/layout/app-shell";
import { TokenGate } from "./features/auth/token-gate";
import { DashboardPage } from "./pages/dashboard";
import { JobDetailPage } from "./pages/job-detail";
import { RepoDetailPage } from "./pages/repo-detail";
import { ReposPage } from "./pages/repos";
import { SettingsPage } from "./pages/settings";

export function App() {
  return (
    <>
    <TokenGate />
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<DashboardPage />} />
        <Route path="repos" element={<ReposPage />} />
        <Route path="repos/:repoId" element={<RepoDetailPage />} />
        <Route path="jobs/:jobId" element={<JobDetailPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
    </>
  );
}
