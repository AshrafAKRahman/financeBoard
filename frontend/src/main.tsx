import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider } from "react-router-dom";

import "@/i18n";
import "./app/styles.css";
import { makeQueryClient } from "./app/providers";
import { makeRouter } from "./app/router";

const queryClient = makeQueryClient();
const root = document.getElementById("root");

if (root) {
  createRoot(root).render(
    <StrictMode>
      <RouterProvider router={makeRouter(queryClient)} />
    </StrictMode>,
  );
}
