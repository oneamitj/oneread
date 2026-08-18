import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { applyConsent } from "./analytics/consent";
import "./styles/tokens.css";
import "./styles/glass.css";
import "./styles/app.css";

applyConsent();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
