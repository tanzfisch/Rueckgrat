FROM caddy:latest

COPY Caddyfile /etc/caddy/Caddyfile

#RUN if [ -n "$HUB_PI" ]; then \
#      sed -i "s/host_placeholder/localhost, $HUB_PI/" /etc/caddy/Caddyfile; \
#    else \
#      sed -i "s/host_placeholder/localhost/" /etc/caddy/Caddyfile; \
#    fi

EXPOSE 80 443