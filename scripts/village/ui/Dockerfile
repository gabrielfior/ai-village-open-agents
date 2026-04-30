# ── build ──────────────────────────────────────────────────────────
FROM node:20-alpine AS builder
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY tsconfig.json vite.config.ts index.html ./
COPY public/ public/
COPY src/ src/
RUN npm run build

# ── runtime ───────────────────────────────────────────────────────
FROM node:20-alpine
WORKDIR /app
COPY --from=builder /app/dist ./dist
COPY server.js .
EXPOSE 80
CMD ["node", "server.js"]
