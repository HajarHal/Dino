import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// En développement, l'API FastAPI tourne sur :8000 (uvicorn ica.api:app --port 8000).
export default defineConfig({
  plugins: [react()],
  // copy/fr.json (textes de l'application) est à la racine du dépôt, partagé avec les tests Python.
  server: { port: 5173, proxy: { "/api": "http://127.0.0.1:8000" }, fs: { allow: [".."] } },
});
