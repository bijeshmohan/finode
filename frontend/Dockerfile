# The React app's own image (the `web` service in compose.yaml): built with Node, served by nginx. Built from the repo
# root (`docker build -f frontend/Dockerfile .`), since the colour tokens, the font and the icons both UIs share live in
# app/static; frontend/Dockerfile.dockerignore keeps everything else out. It holds no settings and no secrets: only
# VITE_API_URL, the API's address, built into the app. Both images are pinned by digest as well as tag. nginx runs as
# its own unprivileged user on port 8080 (nginxinc/nginx-unprivileged), and compose.yaml runs it read-only.

FROM node:26.13.1-alpine@sha256:6bd9ab43c0ec0190ca7b2d193906cb8b7edf6e7f4afa43ddeccd6452710bffb5 AS build
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY app/static /src/app/static
COPY frontend ./
ARG VITE_API_URL
RUN test -n "$VITE_API_URL" || { echo "VITE_API_URL is required, e.g. https://finode.bijesh.me" >&2; exit 1; }
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.30.3-alpine@sha256:b3f2436575bd5be7386518084d842dac414ab4962712afa31e99e0942a56e3b2
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY frontend/nginx-headers.conf /etc/nginx/finode-headers.conf
COPY --from=build /src/frontend/dist /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 CMD wget -q --spider http://127.0.0.1:8080/ || exit 1
