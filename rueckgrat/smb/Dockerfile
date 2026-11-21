# #225 the contacts' files as SMB shares (HUB_FILE_SHARE=smb, the compose profile smb). samba only: the hub writes its
# users and shares into /state (the volume hub_smb, hub/app/utils/sandbox_smb.py), docker's volumes folder is /volumes
FROM debian:bookworm-slim

# libnss-extrausers: the share users are /var/lib/extrausers/passwd, which is /state/passwd (the hub's)
RUN apt-get update && apt-get install -y --no-install-recommends samba libnss-extrausers && \
    rm -rf /var/lib/apt/lists/* && \
    groupadd -g 1000 sandbox && useradd -u 1000 -g 1000 -M -d /nonexistent -s /usr/sbin/nologin sandbox && \
    rm -rf /var/lib/extrausers && ln -s /state /var/lib/extrausers && \
    sed -i -E 's/^(passwd:.*)$/\1 extrausers/' /etc/nsswitch.conf

COPY smb.conf /etc/samba/smb.conf
COPY --chmod=755 entrypoint.sh /entrypoint.sh

EXPOSE 445
ENTRYPOINT ["/entrypoint.sh"]
