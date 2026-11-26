FROM nginxinc/nginx-unprivileged:1.28-alpine

ENV NGINX_ENVSUBST_FILTER="^TRIAGE_API_UPSTREAM$"
COPY default.conf.template /etc/nginx/templates/default.conf.template
COPY index.html /usr/share/nginx/html/dashboard/index.html
COPY assets/ /usr/share/nginx/html/dashboard/assets/
EXPOSE 8080
