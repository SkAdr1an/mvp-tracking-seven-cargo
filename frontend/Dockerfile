FROM node:22-bookworm-slim AS build
WORKDIR /src
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ARG VITE_API_URL=/backend
ARG VITE_WS_URL
ARG VITE_PUBLIC_APP_URL
ENV VITE_API_URL=$VITE_API_URL VITE_WS_URL=$VITE_WS_URL VITE_PUBLIC_APP_URL=$VITE_PUBLIC_APP_URL
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /src/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80 443
