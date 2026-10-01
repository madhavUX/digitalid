# Public booking UI (Next.js App Router)

## Local development

1. Start Django on port 8000.
2. From `frontend/`:

```bash
cp .env.example .env.local
npm install
npm run dev
```

3. Open `http://localhost:3000/book/<location-slug>`.

Browser requests go to `/backend/api/v1/...` and Next.js rewrites them to `DJANGO_API_URL`.

## Scripts

| Script | Purpose |
|---|---|
| `npm run dev` | Dev server |
| `npm run lint` | ESLint |
| `npm run typecheck` | TypeScript |
| `npm run test` | Vitest |
| `npm run build` | Production build |

## Notes

- Django remains authoritative for availability, pricing, and booking.
- Availability is never long-cached; catalog/location may use short HTTP cache from Django.
- Booking create always sends `Idempotency-Key`.
