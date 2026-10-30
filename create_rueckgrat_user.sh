#!/bin/bash
# Creates a user with passwordless sudo and your ssh key on every given machine.
# Usage: ./create_rueckgrat_user.sh USER HOST [HOST...]
# Example: ./create_rueckgrat_user.sh rueckgrat localhost 192.168.2.158
set -e
if [[ $# -lt 2 ]]; then
  echo "Usage: $0 USER HOST [HOST...]" >&2
  exit 1
fi
NEW_USER="$1"
shift
HOSTS="$*"        # your machines, as you reach them with ssh
if [[ ! "$NEW_USER" =~ ^[a-z_][a-z0-9_-]*$ ]]; then
  echo "Invalid user name: $NEW_USER" >&2
  exit 1
fi
PUBKEY="$(cat ~/.ssh/id_ed25519.pub)"
for h in $HOSTS; do
  echo "== $h"
  ssh -t "$h" "sudo bash -c '
    id $NEW_USER >/dev/null 2>&1 || useradd -m -s /bin/bash $NEW_USER
    usermod -aG sudo $NEW_USER 2>/dev/null || usermod -aG wheel $NEW_USER
    echo \"$NEW_USER ALL=(ALL) NOPASSWD: ALL\" > /etc/sudoers.d/$NEW_USER.tmp
    chmod 0440 /etc/sudoers.d/$NEW_USER.tmp
    visudo -cf /etc/sudoers.d/$NEW_USER.tmp && mv /etc/sudoers.d/$NEW_USER.tmp /etc/sudoers.d/$NEW_USER
    install -d -m 700 -o $NEW_USER -g $NEW_USER /home/$NEW_USER/.ssh
    grep -qxF \"$PUBKEY\" /home/$NEW_USER/.ssh/authorized_keys 2>/dev/null || echo \"$PUBKEY\" >> /home/$NEW_USER/.ssh/authorized_keys
    chown $NEW_USER:$NEW_USER /home/$NEW_USER/.ssh/authorized_keys
    chmod 600 /home/$NEW_USER/.ssh/authorized_keys
  '"
  ssh $NEW_USER@"$h" 'sudo -n true && echo "OK: key login and passwordless sudo work"'
done

# in case docker was already installed
for h in $HOSTS; do ssh "$NEW_USER@$h" "sudo usermod -aG docker $NEW_USER"; done