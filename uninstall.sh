#!/bin/bash
# ===============================================
# Rueckgrat Uninstaller
# Removes Rückgrat from machines on the LAN (or the ones given), the reverse of install.sh:
# its containers, images and network, the installer's copy and the chat certificate.
# Data volumes and the models folder only when you say so. Docker, drivers and packages stay.
# --stop only stops the Rückgrat containers and removes nothing.
# Usage: ./uninstall.sh [OPTIONS] [host...]
# ===============================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/install.sh"

# UNINSTALL_CMD - shell code that runs on a host (over ssh or here), set in front of it:
#   ACTION, PURGE_VOLUMES, PURGE_MODELS, DRY_RUN, REMOTE_DIR, MODELS_DIR_DEFAULT
# ACTION: list   - show what is there, exit 3 if nothing
#         status - show the containers, exit 3 if there are none, 4 if none runs
#         stop   - docker stop the running containers, nothing else
#         remove - remove it all (volumes, models: PURGE_*)
# finds everything by the compose project (label com.docker.compose.project=rueckgrat) and the installer's paths
read -r -d '' UNINSTALL_CMD <<'UNINSTALL' || true
say() { printf '%s\n' "$*"; }
run() { say "   \$ $*"; [ "$DRY_RUN" = true ] || "$@"; }
failed=0

d=""
if command -v docker >/dev/null 2>&1; then
    d=docker; docker info >/dev/null 2>&1 || d="sudo -n docker"
fi
p=label=com.docker.compose.project=rueckgrat
containers="" running="" images="" volumes="" networks="" workdirs=""
if [ -n "$d" ]; then
    containers=$($d ps -aq --filter "$p")
    running=$($d ps -q --filter "$p")
    # built by the compose project, the pulled ones its containers run (llama.cpp, cloudflared) and the hub's sandbox image
    # (rueckgrat/sandbox, built only, no compose container runs it: the hub starts its containers)
    images=$( { $d images -q --no-trunc --filter "$p"; $d images -q --no-trunc rueckgrat-sandbox:latest
                [ -z "$containers" ] || $d inspect --format '{{.Image}}' $containers; } | sort -u)
    volumes=$($d volume ls -q --filter "$p")
    networks=$($d network ls -q --filter "$p")
    [ -z "$containers" ] || workdirs=$($d inspect --format '{{ index .Config.Labels "com.docker.compose.project.working_dir" }}' $containers | sort -u)
fi

list_containers() {
    say "   containers:  $($d ps -a --filter "$p" --format '{{.Names}}' | tr '\n' ' ')"
    if [ -n "$running" ]; then
        say "   running:     $($d ps --filter "$p" --format '{{.Names}}' | tr '\n' ' ')"
    else
        say "   running:     none"
    fi
}
if [ "$ACTION" = status ]; then
    [ -n "$d" ] || { say "   (no docker here)"; exit 3; }
    [ -n "$containers" ] || exit 3
    list_containers
    [ -n "$running" ] || exit 4
    exit 0
fi
if [ "$ACTION" = stop ]; then
    if [ -z "$running" ]; then say "   nothing running"; exit 0; fi
    run $d stop $running || failed=1
    exit $failed
fi

# installer folders: the copy in ~/$REMOTE_DIR (also where a downloaded install.sh clones to) is removed,
# any other folder the containers came from is your own checkout and stays
remove_dirs="" keep_dirs="" models=""
for dir in "$HOME/$REMOTE_DIR" $(for w in $workdirs; do dirname "$w"; done); do
    [ -f "$dir/install.sh" ] || continue
    case " $remove_dirs $keep_dirs " in *" $dir "*) continue ;; esac
    if [ "$(basename "$dir")" = "$REMOTE_DIR" ]; then remove_dirs="$remove_dirs $dir"; else keep_dirs="$keep_dirs $dir"; fi
    m=$(sed -n 's/^HOST_MODELS_DIR=//p' "$dir/rueckgrat/.env" 2>/dev/null | tail -n1)
    case " $models " in *" ${m:-$MODELS_DIR_DEFAULT} "*) ;; *) models="$models ${m:-$MODELS_DIR_DEFAULT}" ;; esac
done
[ -n "$models" ] || models=" $MODELS_DIR_DEFAULT"
# a models folder must be a real sub folder, never / or a system or home folder
models_ok=""
for m in $models; do
    [ -d "$m" ] || continue
    case "$m" in
        /*/*) ;;
        *) say "   ⚠️ models folder $m doesn't look right, it stays"; continue ;;
    esac
    case "$m" in
        /home|/home/*/|/root|/usr*|/etc*|/bin*|/sbin*|/lib*|/boot*|/dev*|/proc*|/sys*|/var|/var/lib|/opt|"$HOME"|"$HOME"/)
            say "   ⚠️ models folder $m doesn't look right, it stays"; continue ;;
    esac
    models_ok="$models_ok $m"
done
cert="$HOME/.ssh/rueckgrat-caddy.cert"
[ -f "$cert" ] || cert=""

if [ "$ACTION" = list ]; then
    found=false
    if [ -n "$containers" ]; then found=true; list_containers; fi
    if [ -n "$images" ]; then found=true; say "   images:      $($d image inspect --format '{{join .RepoTags " "}}' $images | tr '\n' ' ')"; fi
    if [ -n "$networks" ]; then found=true; say "   network:     $($d network ls --filter "$p" --format '{{.Name}}' | tr '\n' ' ')"; fi
    if [ -n "$volumes" ]; then found=true; say "   data volumes (database, images, voices, files, caddy): $(echo $volumes)"; fi
    for dir in $remove_dirs; do found=true; say "   folder:      $dir"; done
    for dir in $keep_dirs; do say "   kept:        $dir (your own checkout, not made by the installer)"; done
    for m in $models_ok; do say "   models:      $m ($(du -sh "$m" 2>/dev/null | cut -f1))"; done
    if [ -n "$cert" ]; then found=true; say "   chat cert:   $cert"; fi
    [ -n "$d" ] || say "   (no docker here)"
    if $found; then exit 0; fi
    [ -n "$models_ok" ] && exit 0
    exit 3
fi

# remove: containers first (rm -f stops them), then what they used
if [ -n "$containers" ]; then run $d rm -f $containers || failed=1; fi
if [ -n "$networks" ]; then run $d network rm $networks || failed=1; fi
for i in $images; do
    # by tag, without -f: an image another container still uses stays
    tags=$($d image inspect --format '{{join .RepoTags " "}}' "$i" 2>/dev/null)
    for t in ${tags:-$i}; do
        run $d rmi "$t" || say "   ⚠️ image $t is still in use, it stays"
    done
done
if [ "$PURGE_VOLUMES" = true ] && [ -n "$volumes" ]; then run $d volume rm $volumes || failed=1; fi
cd /
for dir in $remove_dirs; do
    run rm -rf "$dir" 2>/dev/null || run sudo -n rm -rf "$dir" || failed=1
done
if [ -n "$cert" ]; then run rm -f "$cert" || failed=1; fi
if [ "$PURGE_MODELS" = true ]; then
    for m in $models_ok; do
        run sudo -n rm -rf "$m" || failed=1
        # the parent install.sh made for the default folder, only if nothing else is in it
        if [ "$m" = "$MODELS_DIR_DEFAULT" ] && [ -d "$(dirname "$m")" ]; then
            run sudo -n rmdir "$(dirname "$m")" 2>/dev/null || true
        fi
    done
fi
exit $failed
UNINSTALL

# run_uninstall_cmd - UNINSTALL_CMD on a host: here directly, otherwise over its ssh connection (ssh_open_master)
# Usage: run_uninstall_cmd <host> list|status|stop|remove
run_uninstall_cmd() {
    local host="$1" action="$2" vars
    vars="ACTION=$action; PURGE_VOLUMES=$PURGE_VOLUMES; PURGE_MODELS=$PURGE_MODELS; DRY_RUN=$DRY_RUN"
    vars+="; REMOTE_DIR=$REMOTE_DIR; MODELS_DIR_DEFAULT=$HOST_MODELS_DIR_DEFAULT"
    if is_local_host "$host"; then
        sh -s <<< "$vars; $UNINSTALL_CMD"
    else
        ssh_opts "$host"
        ssh "${SSH_OPTS[@]}" "$host" sh -s <<< "$vars; $UNINSTALL_CMD"
    fi
}

# select_uninstall_hosts - menu of the machines with Rückgrat (lan_discover), pick numbers, a = all, or type an IP.
# empty = done. fills UNINSTALL_HOSTS
select_uninstall_hosts() {
    local token i addr verb=Remove
    $STOP && verb=Stop
    $NO_SCAN || lan_discover uninstall
    while true; do
        echo ""
        if (( ${#LAN_ADDRS[@]} )); then
            echo "Machines with Rückgrat on the LAN:"
            for i in "${!LAN_ADDRS[@]}"; do
                printf "   %2d) %s%s\n" $(( i + 1 )) "$(lan_host_label "$i")" \
                    "$([[ " ${UNINSTALL_HOSTS[*]:-} " == *" ${LAN_ADDRS[i]} "* ]] && echo "  [selected]")"
            done
            read_tty "$verb on (numbers, a=all, or type an IP, empty=done): " ""
        else
            read_tty "$verb on host (IP, empty=done): " ""
        fi
        [[ -z "$REPLY" ]] && return 0
        for token in ${REPLY//,/ }; do
            if [[ "$token" == a && ${#LAN_ADDRS[@]} -gt 0 ]]; then
                for addr in "${LAN_ADDRS[@]}"; do add_uninstall_host "$addr"; done
            elif [[ "$token" =~ ^[0-9]+$ ]] && (( token >= 1 && token <= ${#LAN_ADDRS[@]} )); then
                add_uninstall_host "${LAN_ADDRS[token - 1]}"
            elif ( validate_ip "$token" ) >/dev/null; then
                add_uninstall_host "$token"
            else
                echo "   ⚠️ $token: not a number from the list or an IP"
            fi
        done
    done
}

add_uninstall_host() {
    [[ " ${UNINSTALL_HOSTS[*]:-} " == *" $1 "* ]] || UNINSTALL_HOSTS+=("$1")
}

# ask_purge - yes/no for the removal of data, default no. a set flag wins, -y answers no
# Usage: ask_purge <current value: ask|true|false> <question>   (prints true or false)
ask_purge() {
    if [[ "$1" != ask ]]; then echo "$1"; return; fi
    read_tty "$2 (y/N): " "n" "$YES"
    [[ "$REPLY" =~ ^[Yy]$ ]] && echo true || echo false
}

uninstall_usage() {
    echo "Usage: $0 [OPTIONS] [host...]"
    echo "Without hosts it searches the LAN and asks."
    echo "Options:"
    echo "  --user | -u   USER   ssh and sudo user (default: you)"
    echo "  --stop | -s          only stop the Rückgrat containers, remove nothing"
    echo "  --yes | -y           don't ask before removing; data volumes and models stay unless asked for below"
    echo "  --volumes            also delete the data volumes (users, chats, images, voices, files)"
    echo "  --models             also delete the downloaded models"
    echo "  --dry-run            only show what would be removed or stopped"
    echo "  --no-scan            don't search the LAN"
    echo "  --help | -h          show this help"
}

uninstall_main() {
    get_info

    YES=false
    SUDO_USER="$(whoami)"
    SSH_MASTERS=()
    SUDO_CHECKED=()
    SUDO_GRANTED=()
    IN_PLACE=false
    NO_SCAN=false
    DRY_RUN=false
    PURGE_VOLUMES=ask
    PURGE_MODELS=ask
    STOP=false
    LAN_ADDRS=()
    UNINSTALL_HOSTS=()

    trap on_exit EXIT
    trap 'exit 130' INT TERM HUP

    while [[ $# -gt 0 ]]; do
        case $1 in
            -u|--user)
                [[ -n "${2:-}" ]] || { echo "❌ Error: --user requires a username"; exit 1; }
                SUDO_USER="$2"
                shift 2
                ;;
            -y|--yes) YES=true; shift ;;
            -s|--stop) STOP=true; shift ;;
            --volumes) PURGE_VOLUMES=true; shift ;;
            --models) PURGE_MODELS=true; shift ;;
            --dry-run) DRY_RUN=true; shift ;;
            --no-scan) NO_SCAN=true; shift ;;
            -h|--help) uninstall_usage; exit 0 ;;
            -*) echo "Unknown option: $1"; exit 1 ;;
            *) validate_ip "$1"; add_uninstall_host "$1"; shift ;;
        esac
    done

    if $STOP; then print_header "🛑 Rückgrat Stop"; else print_header "🧹 Rückgrat Uninstaller"; fi

    (( ${#UNINSTALL_HOSTS[@]} )) || select_uninstall_hosts
    if (( ${#UNINSTALL_HOSTS[@]} == 0 )); then
        echo "Nothing selected."
        return 0
    fi

    # what is there, per host. sudo first (a password at most once per host, like the installer):
    # docker may need it to see the containers. then per host: remove, only stop, or skip
    local host rc remove=() stop=() failed=()
    for host in "${UNINSTALL_HOSTS[@]}"; do
        print_section
        if is_local_host "$host"; then
            echo "🏠 $host (this machine)"
            sudo_prepare local
        else
            echo "🌐 $host"
            ssh_open_master "$host" || { echo "❌ Error: failed to connect with $host"; failed+=("$host"); continue; }
            sudo_prepare "$host"
        fi
        rc=0
        if $STOP; then
            run_uninstall_cmd "$host" status || rc=$?
            case $rc in
                0) stop+=("$host") ;;
                3) echo "   nothing of Rückgrat here" ;;
                4) echo "   nothing running" ;;
                *) echo "❌ Error: could not check $host"; failed+=("$host") ;;
            esac
            continue
        fi
        run_uninstall_cmd "$host" list || rc=$?
        case $rc in
            0) ;;
            3) echo "   nothing of Rückgrat here"; continue ;;
            *) echo "❌ Error: could not check $host"; failed+=("$host"); continue ;;
        esac
        if $YES; then
            remove+=("$host")
            continue
        fi
        read_tty "   $host: [r] remove Rückgrat, [s] only stop its containers, [n] skip (r/s/N): " "n"
        case "$REPLY" in
            [Rr]) remove+=("$host") ;;
            [Ss]) stop+=("$host") ;;
            *) echo "   skipped" ;;
        esac
    done
    print_section

    if (( ${#remove[@]} + ${#stop[@]} == 0 )); then
        echo "Nothing to do."
        (( ${#failed[@]} == 0 )) && return 0
        return 1
    fi

    for host in "${stop[@]}"; do
        print_section
        echo "🛑 Stopping the Rückgrat containers on $host$($DRY_RUN && echo " (dry run)")"
        run_uninstall_cmd "$host" stop || failed+=("$host")
    done

    if (( ${#remove[@]} )); then
        print_section
        PURGE_VOLUMES=$(ask_purge "$PURGE_VOLUMES" "Also delete the data volumes (users, chats, images, voices, files)? They can't be restored")
        PURGE_MODELS=$(ask_purge "$PURGE_MODELS" "Also delete the downloaded models folder?")
    fi
    for host in "${remove[@]}"; do
        print_section
        echo "🧹 Removing Rückgrat from $host$($DRY_RUN && echo " (dry run)")"
        run_uninstall_cmd "$host" remove || failed+=("$host")
    done
    print_section

    if (( ${#stop[@]} )); then
        echo "🛑 Stopped on ${stop[*]}, they stay stopped (also after a reboot) until you start them again:"
        echo "   docker start \$(docker ps -aq --filter label=com.docker.compose.project=rueckgrat)"
    fi
    if (( ${#remove[@]} == 0 )); then
        if (( ${#failed[@]} )); then
            echo "⚠️ Warning: not done on ${failed[*]}, see above"
            return 1
        fi
        return 0
    fi

    $PURGE_VOLUMES || echo "💾 The data volumes stay (docker volume ls --filter label=com.docker.compose.project=rueckgrat), run again with --volumes to delete them"
    $PURGE_MODELS || echo "💾 The models stay, run again with --models to delete them"
    echo "Docker, the NVIDIA toolkit, packages, the docker group and ssh keys were set up for more than Rückgrat, they stay."
    if (( ${#failed[@]} )); then
        echo "⚠️ Warning: not done on ${failed[*]}, see above"
        return 1
    fi
    echo "Rückgrat removed ✨"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    uninstall_main "$@"
fi
