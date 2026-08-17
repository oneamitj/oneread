import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { applyStoredConsent } from "./analytics/consent";
import "./styles/tokens.css";
import "./styles/glass.css";
import "./styles/app.css";

applyStoredConsent();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
