# Production frontend image — Next.js build + `next start` (not `next dev`).
# Multi-stage: build artifacts only; runtime installs production deps.
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci

FROM node:22-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

ARG DJANGO_API_URL=http://web:8000
ARG NEXT_PUBLIC_API_BASE_URL=/backend
ARG BOOKANYTHING_SITE_DOMAIN=bookanything.in
ENV DJANGO_API_URL=$DJANGO_API_URL
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL
ENV BOOKANYTHING_SITE_DOMAIN=$BOOKANYTHING_SITE_DOMAIN
ENV NEXT_TELEMETRY_DISABLED=1
ENV NODE_ENV=production

RUN npm run build

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV HOSTNAME=0.0.0.0
ENV PORT=3000
# Soft heap cap for 1 vCPU / shared 4 GB VPS (override via compose if needed).
ENV NODE_OPTIONS=--max-old-space-size=384

COPY package.json package-lock.json* ./
RUN npm ci --omit=dev && npm cache clean --force

COPY --from=builder /app/.next ./.next
COPY --from=builder /app/public ./public
COPY --from=builder /app/next.config.ts ./
COPY --from=builder /app/src ./src

EXPOSE 3000
CMD ["npm", "run", "start"]
