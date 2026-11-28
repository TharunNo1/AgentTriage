FROM nginxinc/nginx-unprivileged:1.28-alpine

# Substitute the backend address at startup while preserving nginx variables such as $http_authorization.
ENV NGINX_ENVSUBST_FILTER="^TRIAGE_API_UPSTREAM$"
COPY default.conf.template /etc/nginx/templates/default.conf.template
COPY index.html /usr/share/nginx/html/dashboard/index.html
COPY assets/ /usr/share/nginx/html/dashboard/assets/
EXPOSE 8080
