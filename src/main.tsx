import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import "./styles.css";
import "./desktop-workspace.css";
import "./components/workspace/retained-workspace-layout.css";
import "./components/workspace/page-controls.css";
import "./components/workspace/customer-controls.css";
import "./components/workspace/reading-workspace.css";
import "./components/workspace/august-24-theme.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
