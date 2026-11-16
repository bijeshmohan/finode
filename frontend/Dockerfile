# The React app's own image (the `web` service in compose.yaml): built with Node, served by nginx. Built from the repo
# root (`docker build -f frontend/Dockerfile .`), since the colour tokens, the font and the icons both UIs share live in
# app/static; frontend/Dockerfile.dockerignore keeps everything else out. It holds no settings and no secrets: only
# VITE_API_URL, the API's address, built into the app.

FROM node:26.13.1-alpine AS build
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY app/static /src/app/static
COPY frontend ./
ARG VITE_API_URL
RUN test -n "$VITE_API_URL" || { echo "VITE_API_URL is required, e.g. https://finode.bijesh.me" >&2; exit 1; }
RUN npm run build

FROM nginx:1.30.3-alpine
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY frontend/nginx-headers.conf /etc/nginx/finode-headers.conf
COPY --from=build /src/frontend/dist /usr/share/nginx/html
