FROM nginx:alpine

RUN rm /etc/nginx/conf.d/default.conf
COPY nginx.conf /etc/nginx/conf.d
COPY 504.html /usr/share/nginx/html/504.html
COPY 502.html /usr/share/nginx/html/502.html
