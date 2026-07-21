import { Navigate, Route, Routes } from "react-router-dom";

import { DashboardPage } from "../features/dashboard/DashboardPage";
import { DownloadsPage } from "../features/downloads/DownloadsPage";
import { FeedDetailPage } from "../features/feeds/FeedDetailPage";
import { FeedsPage } from "../features/feeds/FeedsPage";
import { CandidatesPage } from "../features/recognition/CandidatesPage";
import { ReleasesPage } from "../features/releases/ReleasesPage";
import { OperationsPage } from "../features/operations/OperationsPage";
import { SystemPage } from "../features/system/SystemPage";
import { SubscriptionsPage } from "../features/subscriptions/SubscriptionsPage";
import { AppShell } from "./AppShell";
import { AuthGate } from "./AuthGate";

export function App() {
  return (
    <AuthGate>
      <Routes>
        <Route element={<AppShell />}>
          <Route index element={<DashboardPage />} />
          <Route path="feeds" element={<FeedsPage />} />
          <Route path="feeds/:feedId" element={<FeedDetailPage />} />
          <Route path="candidates" element={<CandidatesPage />} />
          <Route path="subscriptions" element={<SubscriptionsPage />} />
          <Route path="downloads" element={<DownloadsPage />} />
          <Route path="releases" element={<ReleasesPage />} />
          <Route path="operations" element={<OperationsPage />} />
          <Route path="system" element={<SystemPage />} />
          <Route path="*" element={<Navigate replace to="/" />} />
        </Route>
      </Routes>
    </AuthGate>
  );
}
