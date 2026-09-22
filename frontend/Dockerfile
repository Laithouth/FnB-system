FROM node:22-slim AS build
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install
COPY . .
ARG VITE_BACKEND_WS_URL=ws://localhost:8000/ws/transcribe
ENV VITE_BACKEND_WS_URL=${VITE_BACKEND_WS_URL}
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
