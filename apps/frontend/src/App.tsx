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

export function App() {
  return (
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
  );
}
