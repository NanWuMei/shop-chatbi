# ChatBI 前端静态资源构建（三阶段：node 构建 → nginx 托管与同源反代）
FROM node:22-alpine AS build
WORKDIR /app
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

FROM nginx:1.27-alpine
# 模板机制：启动时 envsubst 注入 API_UPSTREAM 生成 /etc/nginx/conf.d/default.conf
COPY web/nginx.conf /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
