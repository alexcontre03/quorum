import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import App from "./App";
import { AnalyzePage } from "./pages/AnalyzePage";
import { AskPage } from "./pages/AskPage";
import { CommitmentsBoardPage } from "./pages/CommitmentsBoardPage";
import { CommitmentDetailPage } from "./pages/CommitmentDetailPage";
import { MeetingsPage } from "./pages/MeetingsPage";
import { EvaluationPage } from "./pages/EvaluationPage";
import { ToastProvider } from "./components/Toast";
import { bootstrapTheme } from "./components/ThemeToggle";
import "./styles.css";

bootstrapTheme();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ToastProvider>
      <BrowserRouter>
        <Routes>
          <Route element={<App />}>
            <Route index element={<CommitmentsBoardPage />} />
            <Route path="compromisos/:id" element={<CommitmentDetailPage />} />
            <Route path="analizar" element={<AnalyzePage />} />
            <Route path="reuniones" element={<MeetingsPage />} />
            <Route path="preguntar" element={<AskPage />} />
            <Route path="evaluacion" element={<EvaluationPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </ToastProvider>
  </StrictMode>
);
