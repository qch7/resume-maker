import { createRoot } from "react-dom/client";
import App from "./app/App";
import { reportClientError } from "./shared/lib/api";
import "./styles/index.css";

window.addEventListener("error", (event) =>
  reportClientError(
    "uncaught_error",
    event.error ?? event.message,
    event.filename,
  ),
);
window.addEventListener("unhandledrejection", (event) =>
  reportClientError("unhandled_rejection", event.reason),
);

createRoot(document.getElementById("root")!).render(<App />);
