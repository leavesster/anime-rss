import { Navigate, Route, Routes } from "react-router-dom";

import { DashboardPage } from "../features/dashboard/DashboardPage";
import { FeedDetailPage } from "../features/feeds/FeedDetailPage";
import { FeedsPage } from "../features/feeds/FeedsPage";
import { CandidatesPage } from "../features/recognition/CandidatesPage";
import { ReleasesPage } from "../features/releases/ReleasesPage";
import { AppShell } from "./AppShell";

export function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<DashboardPage />} />
        <Route path="feeds" element={<FeedsPage />} />
        <Route path="feeds/:feedId" element={<FeedDetailPage />} />
        <Route path="candidates" element={<CandidatesPage />} />
        <Route path="releases" element={<ReleasesPage />} />
        <Route path="*" element={<Navigate replace to="/" />} />
      </Route>
    </Routes>
  );
}
