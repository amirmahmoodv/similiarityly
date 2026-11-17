FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY security-headers.conf.template /etc/nginx/snippets/security-headers.conf.template
# Writes config.js and security-headers.conf from API_URL on every start.
COPY --chmod=755 docker-entrypoint.d/40-similarityly-config.sh /docker-entrypoint.d/
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
