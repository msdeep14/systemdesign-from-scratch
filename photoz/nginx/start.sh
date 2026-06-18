#!/bin/sh

# Start nginx in the background
nginx -g "daemon off;" &

# Start consul-template in the foreground
echo "Starting consul-template..."
exec consul-template \
  -consul-addr=127.0.0.1:8500 \
  -template="/etc/nginx/conf.d/nginx.conf.ctmpl:/etc/nginx/conf.d/nginx.conf:nginx -s reload"
