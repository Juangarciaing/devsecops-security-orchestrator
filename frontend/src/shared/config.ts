// Twelve-factor config: read from Vite's `import.meta.env`, never hardcode.
// Module 1 only needs the backend base URL; later modules extend this file
// rather than scattering `import.meta.env.VITE_*` reads across features.
export const apiBaseUrl = import.meta.env.VITE_API_BASE_URL
