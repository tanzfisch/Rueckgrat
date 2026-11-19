"""
Hub management tool (signup invites and users), run inside the hub container:

    docker exec -it rueckgrat_hub python -m app.hub_management invite create
    docker exec -it rueckgrat_hub python -m app.hub_management invite create --email a@b.c --days 3 --max-uses 2
    docker exec -it rueckgrat_hub python -m app.hub_management invite create --nsfw on
    docker exec -it rueckgrat_hub python -m app.hub_management invite list
    docker exec -it rueckgrat_hub python -m app.hub_management invite remove 4
    docker exec -it rueckgrat_hub python -m app.hub_management invite modify 4 --nsfw on
    docker exec -it rueckgrat_hub python -m app.hub_management invite modify 4 --nsfw          (asks: on or off?)
    docker exec -it rueckgrat_hub python -m app.hub_management user create [UserName]
    docker exec -it rueckgrat_hub python -m app.hub_management user create [UserName] --password secret --nsfw
    docker exec -it rueckgrat_hub python -m app.hub_management user list
    docker exec -it rueckgrat_hub python -m app.hub_management user modify [UserName] --nsfw off
    docker exec -it rueckgrat_hub python -m app.hub_management user modify [UserName] --nsfw       (asks: on or off?)
    docker exec -it rueckgrat_hub python -m app.hub_management companion list
    docker exec -it rueckgrat_hub python -m app.hub_management companion list --user [UserName]
    docker exec -it rueckgrat_hub python -m app.hub_management companion status 31
    docker exec -it rueckgrat_hub python -m app.hub_management companion status 31 --log 50 --json
    docker exec -it rueckgrat_hub python -m app.hub_management maintenance status
    docker exec -it rueckgrat_hub python -m app.hub_management maintenance run
    docker exec -it rueckgrat_hub python -m app.hub_management maintenance run --job summaries --all
    docker exec -it rueckgrat_hub python -m app.hub_management stats
    docker exec -it rueckgrat_hub python -m app.hub_management protocol list
    docker exec -it rueckgrat_hub python -m app.hub_management protocol show 12
    docker exec -it rueckgrat_hub python -m app.hub_management protocol show 12 --json
    docker exec -it rueckgrat_hub python -m app.hub_management protocol tools
    docker exec -it rueckgrat_hub python -m app.hub_management offline status
    docker exec -it rueckgrat_hub python -m app.hub_management offline nomad http://192.168.2.177:8080
    docker exec -it rueckgrat_hub python -m app.hub_management offline nomad --clear
    docker exec -it rueckgrat_hub python -m app.hub_management offline simulate on

Whoever can run docker on the host is trusted as admin.
"""
import argparse
import json
import shutil
import textwrap
from datetime import datetime, timezone

from argon2 import PasswordHasher

from app.utils.db import ChatDB
from app.common.logger import RED

DB_PATH = "/hub/db/chat.db"
# placeholder until the real domain is known
SIGNUP_URL = "https://rickratz.com/?invite={token}"

# the row colours of the registry CLI (node/app/registry_manager.py, print_list / print_nodes), copied: hub and node are separate images
GRAY_BG = "\033[48;5;236m"
RESET = "\033[0m"

def print_table(header, rows, width=100, empty=None):
    """a list view like the registry's: the header on gray, then every second row gray. a row is a line or a list of
    lines (one block, one colour). no header: no blank line before it. empty: printed instead of no rows"""
    if header is not None:
        print()
        print(f"{GRAY_BG}{header:<{width}}{RESET}")
    if not rows and empty:
        print(empty)
    for i, row in enumerate(rows):
        for line in [row] if isinstance(row, str) else row:
            print(f"{GRAY_BG if i % 2 else ''}{line:<{width}}{RESET}")


def print_invites(invites):
    header = f"{'ID':<5} {'BY':<12} {'EMAIL':<28} {'USES':<6} {'EXPIRES (UTC)':<17} {'CONTENT':<8} {'STATUS'}"
    lines = []
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for invite in invites:
        expires_at = invite["expires_at"]
        if invite["uses"] >= invite["max_uses"]:
            status = "used"
        elif expires_at is not None and expires_at <= now:
            status = "expired"
        else:
            status = "open"
        # stored as 2026-10-24T20:20:34+00:00, show 2026-10-24 20:20
        expires = expires_at[:16].replace("T", " ") if expires_at else "never"
        email = invite["email"] or "-"
        uses = f"{invite['uses']}/{invite['max_uses']}"
        content = "NSFW" if invite["nsfw_allowed"] else "SFW"
        lines.append(f"{str(invite['id']):<5} {invite['created_by'] or '-':<12} {email:<28} {uses:<6} {expires:<17} {content:<8} {status}")
    print_table(header, lines, empty="No invites")


def print_users(users):
    header = f"{'ID':<5} {'USER':<20} {'CONTENT':<8} {'CREATED (UTC)'}"
    lines = []
    for user in users:
        content = "NSFW" if user["nsfw_allowed"] else "SFW"
        created = (user["created_at"] or "")[:16]
        lines.append(f"{str(user['id']):<5} {user['username']:<20} {content:<8} {created}")
    print_table(header, lines, empty="No users")


def companion_now(db):
    """the hub's companion clock, real time"""
    from app.utils import clock
    return clock.now(), "real time"


def companion_status(db, contact, log_entries):
    """everything about one companion as a dict, times in the user's timezone"""
    from app.utils import clock
    from app.companion.settings import CompanionSettings
    from app.companion.scheduler import CompanionScheduler
    from app.companion.user_tasks import UserTasks
    contact_id = contact["id"]
    tz = clock.user_timezone(db, contact["user_id"])
    def local(text):
        return clock.from_db(text).astimezone(tz).strftime("%a %d %H:%M") if text else None

    now, clock_text = companion_now(db)
    last_run = db.last_companion_run(contact_id)
    status = {
        "contact_id": contact_id, "name": contact["name"], "user": contact["username"], "companion": bool(contact["companion"]),
        "timezone": str(tz), "now": now.astimezone(tz).strftime("%a %Y-%m-%d %H:%M") if now else None, "clock": clock_text,
        "last_run": local(last_run),
        "cutoff": CompanionScheduler(db, None, None).cutoff(contact_id, tz, now).astimezone(tz).strftime("%a %d %H:%M") if now else None,
        "messages_today": db.count_companion_messages(contact_id, clock.local_day(now.astimezone(tz))[0]) if now else None,
        "limits": CompanionSettings(db.get_contact_by_id(contact_id)).limits_text(),
        "calendar": [{"row": r["id"], "due": local(r["due_at"]), "kind": r["kind"], "note": r["note"],
                      "repeat": UserTasks.repeat_text(r["recurrence"]) if r["recurrence"] else "", "alarm": bool(r["alarm"])}
                     for r in db.pending_companion_rows(contact_id)],
        "hub_next_wake": local(db.next_companion_due()),
        "log": [{"at": local(e["at"]), **e["record"], "occurrence": local(e["record"].get("occurrence"))} for e in log_entries],
    }
    return status


def print_companion_status(s):
    print(f"\ncompanion {s['contact_id']} {s['name']} (user {s['user']}): {'ON' if s['companion'] else 'OFF'}")
    print(f"  timezone   {s['timezone']}")
    print(f"  now        {s['now'] or '?'} ({s['clock']})")
    print(f"  last run   {s['last_run'] or 'never'}, catch-up cutoff {s['cutoff'] or '?'}")
    print(f"  messages   {s['messages_today'] if s['messages_today'] is not None else '?'} today, limits {s['limits']}")
    print(f"  next wake  {s['calendar'][0]['due'] if s['calendar'] else '-'} (hub: {s['hub_next_wake'] or '-'})")
    print("  calendar")
    print_table(None, [f"    {r['due']:<12} {r['kind']:<10} {r['repeat']:<15}{'alarm ' if r['alarm'] else ''}{r['note']}"
                       for r in s["calendar"] or [{"due": "", "kind": "nothing pending", "note": "", "repeat": "", "alarm": False}]])
    print(f"  last {len(s['log'])} pass{'' if len(s['log']) == 1 else 'es'}")
    passes = []     # one colour per pass, with its detail lines
    for e in s["log"]:
        due = f" (due {e['occurrence']})" if e["occurrence"] != e["at"] else ""
        block = [f"    {e['at']} {e['kind']} #{e['row']} {e['note']!r}{due}"]
        for key in ("missed", "reflection", "lookup", "plan", "thoughts", "message", "error"):
            if key == "plan" and (e.get("plan") or (e["kind"] == "planning" and "plan" in e)):
                for line in e["plan"] or ["empty plan"]:
                    block.append(f"        {'plan':<10} {line}")
            elif e.get(key):
                block.append(f"        {key:<10} {e[key]}")
        passes.append(block)
    print_table(None, passes)


def maintenance_status(db):
    from app.maintenance import maintenance_tasks, sweeper
    print(f"\nnightly window {sweeper.QUIET_START:%H:%M}-{sweeper.QUIET_END:%H:%M} (each user's timezone), "
          f"at most {sweeper.BATCH} items per task and user and night")
    if sweeper.INTERVAL_MINUTES > 0:
        print(f"during the day every {sweeper.INTERVAL_MINUTES} min, at most {sweeper.SMALL_BATCH} items per task and user")
    else:
        print("no runs during the day (HUB_MAINTENANCE_INTERVAL=0)")
    for task in maintenance_tasks(db, None):
        print(f"  {task.name}")
        print_table(None, [f"    {key:<16} {value if value is not None else '-'}" for key, value in task.status().items()])


def maintenance_run(db, args):
    """runs the pending maintenance now, outside the window, one item at a time on this process.
    it does not see the hub's chats: it does not wait for replies being made"""
    import asyncio
    from app.tasks import TaskQueue
    from app.utils import Infrastructure
    from app.maintenance import MaintenanceSweeper, maintenance_tasks, sweeper
    infrastructure = Infrastructure()
    asyncio.run(infrastructure.connect_nodes(connect=False))   # chat and embed go over http, no websocket next to the hub's
    tasks = maintenance_tasks(db, infrastructure)
    if args.job and args.job not in [t.name for t in tasks]:
        print(f"unknown job {args.job}, known: {', '.join(t.name for t in tasks)}")
        return
    user_id = None
    if args.user:
        user_id = db.get_user_id(args.user)
        if user_id is None:
            print("user not found")
            return
    MaintenanceSweeper(db, TaskQueue(max_parallel=1), tasks).sweep(user_id, None if args.all else sweeper.BATCH, [args.job] if args.job else None)
    maintenance_status(db)


def offline_command(args, settings=None, http_get=None):
    """offline status / nomad / simulate: the hub settings of the offline features (HubSettings, the running hub picks a
    change up within seconds, NOMAD on its next probe), no restart"""
    import requests
    from app.utils.hub_settings import HubSettings
    from app.utils.library import LibraryError
    from app.utils.nomad import Nomad, normalize_nomad_url
    settings = settings or HubSettings()
    http_get = http_get or requests.get
    if args.action == "simulate":
        settings.set("simulate_offline", "1" if args.state == "on" else "")
        print("simulated offline on: the hub uses no internet (web search, Wikipedia, maps, rates, public links) and takes "
              "the offline ways" if args.state == "on" else "simulated offline off: the hub probes the internet again")
        return
    if args.action == "nomad":
        if args.clear:
            settings.set("nomad_url", "")
            print("NOMAD switched off (also against NOMAD_URL in .env)")
            return
        if args.reset:
            settings.reset("nomad_url")
            print(f"NOMAD from .env again: {settings.get('nomad_url') or 'not set'}")
            return
        url = normalize_nomad_url(args.url or "")
        if not url:
            print("give the NOMAD url, e.g. http://192.168.2.177:8080, or --clear / --reset")
            return
        try:
            ok = http_get(f"{url}/api/health", timeout=5).status_code == 200
        except Exception:
            ok = False
        settings.set("nomad_url", url)
        print(f"NOMAD set to {url}" + ("" if ok else f" (not reachable right now, {url}/api/health did not answer)"))
        return
    url = settings.get("nomad_url")
    nomad = Nomad(lambda: url, http_get)
    nomad.probe()
    library, offline_map = nomad.library(), nomad.offline_map()
    library_text = "not there"
    if library:
        try:
            library_text = f"{library.base_url()}, {len(library.books())} books"
        except LibraryError as e:
            library_text = f"{library.base_url()}, {e}"
    print_table(f"{'SETTING':<20} VALUE", [
        f"{'nomad':<20} {normalize_nomad_url(url) or 'not set'} ({settings.source('nomad_url')})",
        f"{'library':<20} {library_text}",
        f"{'offline map':<20} {f'{len(offline_map.archives())} map file(s)' if offline_map else 'not there'}",
        f"{'simulated offline':<20} {'on' if settings.get('simulate_offline') == '1' else 'off'}",
    ])


def add_nsfw_switch(cmd):
    # "--nsfw on" / "--nsfw off", or just "--nsfw" (value None) to be asked
    cmd.add_argument("--nsfw", nargs="?", choices=["on", "off"], required=True,
                     help="on = NSFW allowed, off = SFW only, leave out on/off to be asked")


def resolve_nsfw(value):
    # returns True for on, False for off, asks until it gets on or off
    while value not in ("on", "off"):
        value = input("NSFW on or off? ").strip().lower()
    return value == "on"


def main():
    parser = argparse.ArgumentParser(
        prog="python -m app.hub_management",
        description="hub management: signup invites, users and the offline features",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""commands:
  invite create [--email EMAIL] [--days N] [--max-uses N] [--nsfw on|off]
                  create an invite and print its token
      --email     only this email may use the invite
      --days      days until expiry, 0 for never (default 7)
      --max-uses  how many signups the invite allows (default 1)
      --nsfw      on = the invited user may use NSFW settings, off = SFW only (default off)
  invite list     list all invites, 'email': None means not bound
  invite remove ID
                  delete an invite by its id (see invite list)
  invite modify ID --nsfw [on|off]
                  allow (on) or forbid (off) NSFW for an invite, asks if on/off is left out
                  (only for signups from now on)

  user create NAME [--password PASSWORD] [--nsfw]
                  create a user directly, without an invite
      --password  password to log in with (default empty = log in with an empty password)
      --nsfw      the user may use NSFW settings (default off = SFW only)
  user list       list all users and their NSFW permission
  user modify NAME --nsfw [on|off]
                  allow (on) or forbid (off) NSFW for a user, asks if on/off is left out
                  (takes effect on their next login)

  companion list [--user NAME]
                  the companions (and contacts with a companion log), or all contacts of a user
  companion status CONTACT_ID [--log N] [--json]
                  a companion's state: clock, calendar, catch-up cutoff, messages today and its last N passes
                  (default 10). read only, safe next to the running hub

  maintenance status
                  the nightly maintenance: window, and per job what is done and what waits (e.g. summaries)
  maintenance run [--job NAME] [--all] [--user NAME]
                  run the waiting maintenance now instead of at night (one item at a time, uses the llm)
      --job       only this job (e.g. summaries), default all
      --all       everything that waits, e.g. the first backfill, default at most one night's batch
      --user      only this user's items

  stats [--minutes N]
                  running agent jobs, users, and users active in the last N minutes (default 10). read only
                  active = wrote a message, logged in or refreshed their login in that time

  protocol list [--limit N]
                  the agent jobs' protocols (decision traces) of about the last day, newest first (default 20). read only
  protocol show PROTOCOL_ID [--json] [--full]
                  one protocol (see protocol list): its plan and lines, times in UTC. long texts clipped to 3 lines,
                  --full: in full. --json: plan, lines, tool calls and outputs. read only
  protocol tools  the tool calls of the stored protocols per tool: calls, failures, durations, last error. read only
                  grouped by step, workers indented, long values wrapped and clipped to a few lines
      --full      long values in full

  offline status  the offline features: the NOMAD url (and where it comes from), its library and map, simulated offline
  offline nomad URL | --clear | --reset
                  where Project NOMAD runs (offline library and map, the fallbacks without internet), --clear: none
                  (also against NOMAD_URL in .env), --reset: back to NOMAD_URL from .env. no restart needed
  offline simulate on|off
                  on: the hub acts as if there were no internet (testing the offline fallbacks), the LAN still works""",
    )
    # two levels of subcommands: first the noun (invite/user), then the action
    nouns = parser.add_subparsers(dest="noun", required=True)

    # --- invite ---
    invite = nouns.add_parser("invite", help="manage signup invites")
    invite_actions = invite.add_subparsers(dest="action", required=True)

    create = invite_actions.add_parser("create", help="create an invite and print its token")
    create.add_argument("--email", default=None, help="only this email may use the invite")
    create.add_argument("--days", type=float, default=7, help="days until expiry, 0 for never (default 7)")
    create.add_argument("--max-uses", type=int, default=1, help="how many signups the invite allows (default 1)")
    create.add_argument("--nsfw", choices=["on", "off"], default="off", help="on = the invited user may use NSFW settings, off = SFW only (default off)")

    invite_actions.add_parser("list", help="list all invites")

    remove = invite_actions.add_parser("remove", help="delete an invite")
    remove.add_argument("id", type=int, help="invite id as shown by invite list")

    invite_modify = invite_actions.add_parser("modify", help="change an invite's NSFW permission")
    invite_modify.add_argument("id", type=int, help="invite id as shown by invite list")
    add_nsfw_switch(invite_modify)

    # --- user ---
    user = nouns.add_parser("user", help="manage users")
    user_actions = user.add_subparsers(dest="action", required=True)

    user_create = user_actions.add_parser("create", help="create a user without an invite")
    user_create.add_argument("name", help="user name to log in with")
    user_create.add_argument("--password", default="", help="password to log in with (default empty)")
    user_create.add_argument("--nsfw", action="store_true", help="the user may use NSFW settings (default off = SFW only)")

    user_actions.add_parser("list", help="list all users and their NSFW permission")

    user_modify = user_actions.add_parser("modify", help="change a user's NSFW permission")
    user_modify.add_argument("name", help="user name as shown by user list")
    add_nsfw_switch(user_modify)

    # --- companion (read only) ---
    companion = nouns.add_parser("companion", help="look at the companions (read only)")
    companion_actions = companion.add_subparsers(dest="action", required=True)
    companion_list = companion_actions.add_parser("list", help="the companions, or all contacts of a user")
    companion_list.add_argument("--user", default=None, help="user name as shown by user list")
    status = companion_actions.add_parser("status", help="a companion's state and its last passes")
    status.add_argument("contact_id", type=int, help="contact id as shown by companion list")
    status.add_argument("--log", type=int, default=10, help="how many of the last passes (default 10, at most 50 are kept)")
    status.add_argument("--json", action="store_true", help="print json")

    # --- maintenance ---
    maintenance = nouns.add_parser("maintenance", help="the nightly maintenance (summaries of the conversations)")
    maintenance_actions = maintenance.add_subparsers(dest="action", required=True)
    maintenance_actions.add_parser("status", help="what is done and what waits, read only")
    run = maintenance_actions.add_parser("run", help="run the waiting maintenance now")
    run.add_argument("--job", default=None, help="only this job, e.g. summaries")
    run.add_argument("--all", action="store_true", help="everything that waits, not just one night's batch")
    run.add_argument("--user", default=None, help="user name as shown by user list")

    # --- stats (read only) ---
    stats = nouns.add_parser("stats", help="running agent jobs, users and active users, read only")
    stats.add_argument("--minutes", type=int, default=10, help="active in the last N minutes (default 10)")

    # --- protocol (read only) ---
    protocol = nouns.add_parser("protocol", help="the decision traces of the agent jobs, task and companion passes, read only")
    protocol_actions = protocol.add_subparsers(dest="action", required=True)
    protocol_list = protocol_actions.add_parser("list", help="the protocols of about the last day, newest first")
    protocol_list.add_argument("--limit", type=int, default=20, help="at most N protocols (default 20)")
    protocol_show = protocol_actions.add_parser("show", help="all lines of one protocol")
    protocol_show.add_argument("protocol_id", type=int, help="protocol id as shown by protocol list")
    protocol_show.add_argument("--json", action="store_true", help="the lines as json")
    protocol_show.add_argument("--full", action="store_true", help="long texts in full, not clipped to a few lines")
    protocol_actions.add_parser("tools", help="failures and durations per tool over the stored protocols")

    # --- offline (hub settings, no restart) ---
    offline = nouns.add_parser("offline", help="the offline features: Project NOMAD and simulated offline")
    offline_actions = offline.add_subparsers(dest="action", required=True)
    offline_actions.add_parser("status", help="NOMAD, its library and map, simulated offline")
    nomad = offline_actions.add_parser("nomad", help="set, clear or reset the NOMAD url")
    nomad.add_argument("url", nargs="?", default=None, help="e.g. http://192.168.2.177:8080")
    nomad.add_argument("--clear", action="store_true", help="no NOMAD, also against NOMAD_URL in .env")
    nomad.add_argument("--reset", action="store_true", help="NOMAD_URL from .env again")
    simulate = offline_actions.add_parser("simulate", help="act as if there were no internet")
    simulate.add_argument("state", choices=["on", "off"])

    args = parser.parse_args()
    if args.noun == "offline":
        offline_command(args)
        return
    if args.noun == "protocol":
        print_protocols(ChatDB.read_only(DB_PATH), args)
        return
    if args.noun == "stats":
        s = ChatDB.read_only(DB_PATH).hub_stats(args.minutes)
        print_table(f"{'STAT':<24} VALUE", [f"{'running agent jobs':<24} {s['running_agent_jobs']}", f"{'users':<24} {s['users']}",
                                             f"{f'active last {args.minutes} min':<24} {s[f'active_last_{args.minutes}min']}"])
        return
    if args.noun == "maintenance" and args.action == "status":
        maintenance_status(ChatDB.read_only(DB_PATH))
        return
    if args.noun == "companion":
        db = ChatDB.read_only(DB_PATH)
        if args.action == "list":
            rows = db.companion_contacts(user_name=args.user)
            print_table(f"{'ID':<5} {'USER':<16} {'CONTACT':<20} {'COMPANION':<10} {'PENDING':<8} LAST PASS (UTC)",
                        [f"{r['id']:<5} {r['username']:<16} {r['name'][:20]:<20} {'on' if r['companion'] else 'off':<10} {r['pending']:<8} {r['last_pass'] or '-'}"
                         for r in rows], empty="No companions")
        else:
            contacts = db.companion_contacts(contact_id=args.contact_id)
            if not contacts:
                print("not found")
                return
            s = companion_status(db, contacts[0], db.get_companion_log(args.contact_id, args.log))
            if args.json:
                print(json.dumps(s, indent=2, ensure_ascii=False))
            else:
                print_companion_status(s)
        return
    db = ChatDB(DB_PATH)

    if args.noun == "invite":
        if args.action == "create":
            if args.max_uses < 1:
                parser.error("--max-uses must be at least 1")
            token = db.create_invite("no name", args.email, args.days or None, args.max_uses, args.nsfw == "on")
            print(f"created new token: {token}")
            print(f"signup url: {SIGNUP_URL.format(token=token)}")
        elif args.action == "list":
            print_invites(db.get_invites())
        elif args.action == "remove":
            print("removed" if db.remove_invite(args.id) else "not found")
        elif args.action == "modify":
            nsfw = resolve_nsfw(args.nsfw)
            ok = db.set_invite_nsfw(args.id, nsfw)
            print(f"invite {args.id}: {'NSFW' if nsfw else 'SFW'}" if ok else "not found")
    elif args.noun == "maintenance":
        maintenance_run(db, args)
    elif args.noun == "user":
        if args.action == "create":
            # same hashing as signup in main.py (argon2). An empty password is hashed too,
            # so login with an empty password works (verify_password rejects a missing hash)
            user_id = db.create_user(args.name, PasswordHasher().hash(args.password), args.nsfw)
            if user_id is None:
                print("user already exists")
            else:
                print(f"created user {args.name} (id {user_id}), {'NSFW' if args.nsfw else 'SFW'}")
        elif args.action == "list":
            print_users(db.get_users_admin())
        elif args.action == "modify":
            nsfw = resolve_nsfw(args.nsfw)
            ok = db.set_user_nsfw(args.name, nsfw)
            print(f"{args.name}: {'NSFW' if nsfw else 'SFW'} (on their next login)" if ok else "not found")

def print_protocols(db, args):
    """#174 protocol list / show / tools"""
    if args.action == "list":
        rows = db.get_protocols(args.limit)
        dash = lambda value: "-" if value is None else value    # a pass has no conversation or message when it starts
        print_table(f"{'ID':<5} {'CREATED (UTC)':<20} {'KIND':<10} {'CONV':<6} {'MSG':<7} {'STATUS':<12} {'LINES':<6} {'TOOLS':<6} {'FAILED':<7} JOB",
                    [f"{r['id']:<5} {r['created_at']:<20} {r['kind']:<10} {dash(r['conversation_id']):<6} {dash(r['message_id']):<7} {r['status'] or '-':<12} "
                     f"{r['lines']:<6} {r['tool_calls']:<6} {r['failed_calls']:<7} {r['name']}" for r in rows], empty="No protocols")
        return
    if args.action == "tools":
        rows = db.protocol_tool_stats()
        print_table(f"{'TOOL':<22} {'CALLS':>6} {'FAILED':>7} {'FAIL%':>6} {'AVG MS':>8} {'MAX MS':>8}  LAST ERROR",
                    [f"{r['tool'][:22]:<22} {r['calls']:>6} {r['failed']:>7} {100 * r['failed'] // r['calls']:>5}% {r['avg_ms'] or 0:>8} "
                     f"{r['max_ms'] or 0:>8}  {' '.join(str(r['last_error'] or '-').split())[:37]}" for r in rows], empty="No tool calls")
        return
    protocol = db.get_protocol(args.protocol_id)
    if protocol is None:
        print("not found")
        return
    if args.json:
        print(json.dumps(protocol, indent=2, ensure_ascii=False))
        return
    print_protocol(protocol, args.full)


CLIPPED_LINES = 3       # protocol show: a long text is clipped to this many lines (--full: not clipped)

def wrap_text(text, width, full, indent):
    """a long text for protocol show: its own line breaks kept, wrapped to the width, clipped to CLIPPED_LINES"""
    rows = [row for part in str(text).splitlines() for row in (textwrap.wrap(part, width - len(indent) - 2, subsequent_indent="  ") or [""])]
    if not full and len(rows) > CLIPPED_LINES:
        rows = rows[:CLIPPED_LINES] + [f"… {len(rows) - CLIPPED_LINES} more lines"]
    return [indent + row for row in rows]

def short_value(value):
    """a line's data value on the action's line: [{task, role}] as "t5 analyst", lists joined, bools as true / false"""
    if isinstance(value, list):
        return ", ".join(f"{v.get('task')} {v.get('role')}" if isinstance(v, dict) else str(v) for v in value) or "-"
    return json.dumps(value) if isinstance(value, bool) else " ".join(str(value).split())

def print_protocol(protocol, full=False, width=None):
    """protocol show: the current plan, then a table of the lines, striped like print_table: time, step, task, agent,
    ok, action and the short data. the long texts (outputs, a tool call's args) follow indented with their line breaks,
    clipped. a heading per step of the plan, workers indented under the controller, failures red"""
    width = (width or shutil.get_terminal_size((120, 24)).columns) - 1     # not up to the edge: the terminal would wrap the padding
    outputs = {ref: o["text"] for ref, o in protocol.get("outputs", {}).items()}
    calls = {c["call"]: c for c in protocol.get("tool_calls", [])}
    print()
    print("\n".join(textwrap.wrap(f"protocol {protocol['id']} ({protocol.get('kind', 'job')}, {protocol.get('status', '-')}): "
                                   f"conversation {protocol['conversation_id'] or '-'}, message {protocol['message_id'] or '-'}, "
                                   f"job {protocol['job_id']}, created {protocol['created_at']} UTC", width, subsequent_indent="  ")))
    plan = protocol.get("plan")
    if plan:
        print(f"plan revision {plan['revision']}: {plan['name']}")
        for i, step in enumerate(plan["steps"], 1):
            for task in step:
                prompt = task.get("prompt", outputs.get((task.get("out") or {}).get("prompt"), ""))
                print(f"  step {i}  {task['task']:<4} {task['role']}")
                print("\n".join(wrap_text(prompt, width, full, " " * 13)))
    print(f"{GRAY_BG}{'TIME (UTC)   STEP TASK AGENT                    OK ACTION        DETAILS':<{width}}{RESET}")
    if not protocol["lines"]:
        print("no lines")
    stripe = 0
    for line in protocol["lines"]:
        data = dict(line.get("data") or {})
        if line["action"] == "step_started":
            heading = f"── step {line['step']}/{data.get('total')}: {short_value(data.get('roles') or [])} "
            print(f"{heading:─<{width}}")
            continue
        if line["action"] == "retry":
            heading = f"── step {line['step']}: retry {line['task'] or ''} {data.get('role', '')}, attempt {data.get('attempt')} "
            print(f"{heading:─<{width}}")
        worker = line["agent"] != "controller"
        indent = "    " if worker else ""
        agent = f"{line['agent'][:14]} {line['agent_id'][-8:]}" if worker else "controller"
        ok = {True: "✓", False: "✗"}.get(line["ok"], "")
        refs = data.pop("out", {})
        short = "  ".join(f"{k}={short_value(v)}" for k, v in data.items())
        head = (f"{line['at'][11:23]} {line['step'] if line['step'] is not None else '':<4} {line['task'] or '':<4} "
                f"{indent}{agent:<{24 - len(indent)}} {ok:<2} {line['action']:<13} {short}")
        pad = " " * 23 + indent + "  "
        rows = textwrap.wrap(head, width, subsequent_indent=pad) or [head]
        call = calls.get(data.get("call")) if line["action"] == "tool_call" else None
        if call and call["args"]:       # each argument on its own, a code's line breaks kept
            try:
                args = json.loads(call["args"])
            except ValueError:
                args = {"args": call["args"]}
            for key, value in (args.items() if isinstance(args, dict) else [("args", args)]):
                rows += wrap_text(f"{key}: {value}", width, full, pad)
        for key, ref in refs.items():
            rows += wrap_text(f"{key}: {outputs.get(ref, f'({ref} missing)')}", width, full, pad)
        failed = line["ok"] is False or line["action"] in ("failed", "timed_out") or data.get("status") == "failed"
        bg = GRAY_BG if stripe % 2 else ""
        for row in rows:
            print(f"{bg}{RED if failed else ''}{row:<{width}}{RESET}")
        stripe += 1

if __name__ == "__main__":
    main()
