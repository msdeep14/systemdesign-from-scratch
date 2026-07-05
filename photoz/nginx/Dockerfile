FROM nginx:alpine

RUN apk add --no-cache curl unzip && \
    curl -o /tmp/consul-template.zip https://releases.hashicorp.com/consul-template/0.37.0/consul-template_0.37.0_linux_amd64.zip && \
    unzip /tmp/consul-template.zip -d /usr/local/bin/ && \
    rm /tmp/consul-template.zip && \
    apk del curl unzip

RUN rm /etc/nginx/conf.d/default.conf
COPY error.html /usr/share/nginx/html/error.html
COPY 504.html /usr/share/nginx/html/504.html
COPY 502.html /usr/share/nginx/html/502.html
COPY 500.html /usr/share/nginx/html/500.html

COPY start.sh /start.sh
RUN chmod +x /start.sh

COPY nginx.conf.ctmpl /etc/nginx/conf.d/nginx.conf.ctmpl

CMD ["/start.sh"]
