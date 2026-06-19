# syntax=docker/dockerfile:1

FROM ghcr.io/linuxserver/baseimage-selkies:ubunturesolute

ARG HUB_CERT

RUN if [ -z "$HUB_CERT" ]; then echo "Error: HUB_CERT build arg is required. Use --build-arg HUB_CERT=filename"; exit 1; fi

ENV TITLE=Rueckgrat \
    PIXELFLUX_WAYLAND=true \
    HUB_CERT=${HUB_CERT}

RUN apt-get update && \
  apt-get install -y --no-install-recommends firefox git && \
  rm -rf \
    /config/.cache \
    /config/.launchpadlib \
    /var/lib/apt/lists/* \
    /var/tmp/* \
    /tmp/*

RUN git clone -b 'feature/#73_improving_installer' https://github.com/tanzfisch/Rueckgrat.git || (echo "Clone fehlgeschlagen" && exit 1)

RUN cd Rueckgrat && ./install.sh --chat_only -y

COPY /root /
COPY ${HUB_CERT} /root/.ssh/caddy-root.crt
RUN chmod 600 /root/.ssh/caddy-root.crt

EXPOSE 3001

ENTRYPOINT [./run.sh]
