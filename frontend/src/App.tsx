import { Route, Routes } from "react-router-dom";

import { ConfirmProvider } from "./components/ConfirmDialog";
import Layout from "./components/Layout";
import { ToastProvider } from "./components/Toaster";
import { useEventStream } from "./lib/useEvents";
import AlbumPage from "./pages/AlbumPage";
import LibraryPage from "./pages/LibraryPage";
import QueuePage from "./pages/QueuePage";
import SearchPage from "./pages/SearchPage";
import SettingsPage from "./pages/SettingsPage";
import ToolsPage from "./pages/ToolsPage";

export default function App() {
  useEventStream();
  return (
    <ToastProvider>
      <ConfirmProvider>
        <Layout>
          <Routes>
            <Route path="/" element={<SearchPage />} />
            <Route path="/album/:provider/:id" element={<AlbumPage />} />
            <Route path="/library" element={<LibraryPage />} />
            <Route path="/queue" element={<QueuePage />} />
            <Route path="/tools" element={<ToolsPage />} />
            <Route path="/settings" element={<SettingsPage />} />
          </Routes>
        </Layout>
      </ConfirmProvider>
    </ToastProvider>
  );
}
