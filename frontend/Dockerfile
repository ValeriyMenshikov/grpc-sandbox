# Сборка SPA в node, раздача и прокси /api — в nginx; node_modules в runtime не попадает
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
# envsubst штатного entrypoint подставляет только эти переменные, nginx-овские ($uri, $host)
# остаются как есть; NGINX_LOCAL_RESOLVERS — DNS контейнера из /etc/resolv.conf
ENV NGINX_ENVSUBST_FILTER="^(GATEWAY_URL|NGINX_LOCAL_RESOLVERS)$" \
    NGINX_ENTRYPOINT_LOCAL_RESOLVERS=1 \
    GATEWAY_URL=http://gateway:8080
COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
