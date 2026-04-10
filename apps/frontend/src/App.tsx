import { Routes, Route } from "react-router-dom";
import { Layout } from "./components/Layout";
import { DashboardPage } from "./pages/DashboardPage";
import { CompaniesPage } from "./pages/CompaniesPage";
import { CompanyDetailPage } from "./pages/CompanyDetailPage";
import { PortfolioPage } from "./pages/PortfolioPage";
import { NewsPage } from "./pages/NewsPage";
import { MapPage } from "./pages/MapPage";
import { CountryPage } from "./pages/CountryPage";
import { ChatPage } from "./pages/ChatPage";
import { ScreenerPage } from "./pages/ScreenerPage";
import { useAlertStream } from "./hooks/useAlertStream";
import { AlertStreamContext } from "./contexts/AlertStreamContext";
import { FlashOverlay } from "./components/alerts/FlashOverlay";

export function App() {
  // userId is null until auth is wired — hook no-ops gracefully (no WS opened).
  const { criticalQueue, recentAlerts, dequeueCritical } = useAlertStream(null);

  return (
    <AlertStreamContext.Provider value={{ criticalQueue, recentAlerts, dequeueCritical }}>
      {/* Flash overlay — renders on top of all page content (z-9999) */}
      {criticalQueue.length > 0 && (
        <FlashOverlay
          key={criticalQueue[0].alert_id}
          alert={criticalQueue[0]}
          onDismiss={dequeueCritical}
        />
      )}
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/companies" element={<CompaniesPage />} />
          <Route path="/companies/:id" element={<CompanyDetailPage />} />
          <Route path="/portfolio" element={<PortfolioPage />} />
          <Route path="/news" element={<NewsPage />} />
          <Route path="/map" element={<MapPage />} />
          <Route path="/countries/:code" element={<CountryPage />} />
          <Route path="/chat" element={<ChatPage />} />
          <Route path="/screener" element={<ScreenerPage />} />
        </Route>
      </Routes>
    </AlertStreamContext.Provider>
  );
}
