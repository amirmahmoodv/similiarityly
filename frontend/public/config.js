// Runtime settings. In Docker this file is rewritten at container start from the
// API_URL variable (frontend/docker-entrypoint.d/40-similarityly-config.sh).
// apiUrl "" = the API is on this same origin under /api (nginx or the Vite proxy).
window.__SIM_CONFIG__ = { apiUrl: "" };
