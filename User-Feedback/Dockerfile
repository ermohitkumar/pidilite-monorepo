FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:20-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# Build-time args (NEXT_PUBLIC_* must be present at build because they're inlined)
ARG AUTH_SECRET
ARG NEXT_PUBLIC_APP_URL
ARG NEXT_PUBLIC_NODE_ENV
ARG NEXT_PUBLIC_BACKEND_API_URL
ARG AZURE_AD_CLIENT_ID
ARG AZURE_AD_CLIENT_SECRET
ARG AZURE_AD_TENANT_ID

ENV AUTH_SECRET=$AUTH_SECRET
ENV NEXT_PUBLIC_APP_URL=$NEXT_PUBLIC_APP_URL
ENV NEXT_PUBLIC_NODE_ENV=$NEXT_PUBLIC_NODE_ENV
ENV NEXT_PUBLIC_BACKEND_API_URL=$NEXT_PUBLIC_BACKEND_API_URL
ENV AZURE_AD_CLIENT_ID=$AZURE_AD_CLIENT_ID
ENV AZURE_AD_CLIENT_SECRET=$AZURE_AD_CLIENT_SECRET
ENV AZURE_AD_TENANT_ID=$AZURE_AD_TENANT_ID

RUN npm run build

FROM node:20-alpine AS runner

WORKDIR /app

RUN addgroup --system --gid 1001 nodejs && adduser --system --uid 1001 nextjs

ARG AUTH_SECRET
ARG NEXT_PUBLIC_APP_URL
ARG NEXT_PUBLIC_NODE_ENV
ARG NEXT_PUBLIC_BACKEND_API_URL
ARG AZURE_AD_CLIENT_ID
ARG AZURE_AD_CLIENT_SECRET
ARG AZURE_AD_TENANT_ID

ENV AUTH_SECRET=$AUTH_SECRET
ENV NEXT_PUBLIC_APP_URL=$NEXT_PUBLIC_APP_URL
ENV NEXT_PUBLIC_NODE_ENV=$NEXT_PUBLIC_NODE_ENV
ENV NEXT_PUBLIC_BACKEND_API_URL=$NEXT_PUBLIC_BACKEND_API_URL
ENV AZURE_AD_CLIENT_ID=$AZURE_AD_CLIENT_ID
ENV AZURE_AD_CLIENT_SECRET=$AZURE_AD_CLIENT_SECRET
ENV AZURE_AD_TENANT_ID=$AZURE_AD_TENANT_ID

# Copy build artifacts with correct ownership for the nextjs user.
# The missing --chown on public was likely causing the image optimizer null error.
COPY --from=builder --chown=nextjs:nodejs /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next ./.next
COPY --from=builder --chown=nextjs:nodejs /app/node_modules ./node_modules
COPY --from=builder --chown=nextjs:nodejs /app/package.json ./package.json

USER nextjs
EXPOSE 3000
ENV PORT=3000

CMD ["npx", "next", "start", "-H", "0.0.0.0", "-p", "3000"]