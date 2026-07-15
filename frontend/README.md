# Frontend

Vite + React + TypeScript + Tailwind CSS v4 scaffold for the DevSecOps
Security Orchestrator. Module 1 walking skeleton only — `src/features/` is
intentionally empty until later modules add real features.

## Layout

- `src/app/` — application root component
- `src/features/` — feature slices (empty in module 1)
- `src/shared/` — cross-feature utilities/config (`config.ts` reads `VITE_*` env vars)

## Local development

```bash
cp .env.example .env
npm install
npm run dev
```

## Scripts

| Command | Purpose |
|---|---|
| `npm run dev` | Vite dev server with HMR |
| `npm run build` | Type-check + production build |
| `npm run lint` | ESLint |
| `npm run format:check` | Prettier check (`format` to write) |
| `npm run typecheck` | `tsc -b --noEmit` |
| `npm run test` | Vitest (single run) |
