# Build context: repository root. GATEWAY_URL is baked into the rewrite at build time.
FROM node:22.19.0-alpine AS dependencies
WORKDIR /app
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci

FROM dependencies AS builder
COPY apps/web/ ./
ARG GATEWAY_URL=http://api-gateway:3000
ENV GATEWAY_URL=$GATEWAY_URL NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:22.19.0-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 HOSTNAME=0.0.0.0 PORT=3100
COPY --from=builder --chown=node:node /app/.next/standalone ./
COPY --from=builder --chown=node:node /app/.next/static ./.next/static
COPY --from=builder --chown=node:node /app/public ./public
USER node
EXPOSE 3100
CMD ["node", "server.js"]
