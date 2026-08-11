FROM ghcr.io/linuxserver/baseimage-selkies:ubunturesolute

RUN apt-get update && \
    apt-get install -y --no-install-recommends iputils-ping git nmap vim alsa-utils && \
    rm -rf \
    /config/.cache \
    /config/.launchpadlib \
    /var/lib/apt/lists/* \
    /var/tmp/* \
    /tmp/*

COPY root/ /

COPY requirements.txt .
RUN pip install -r requirements.txt

RUN python -m spacy download en_core_web_sm

WORKDIR /chat

RUN mkdir -p /chat/cache /chat/models && chown -R abc:abc /chat

COPY app app

EXPOSE 3001

VOLUME /config

