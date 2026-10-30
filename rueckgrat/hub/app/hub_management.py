"""
Hub management tool (signup invites and users), run inside the hub container:

    docker exec -it rueckgrat_hub python -m app.hub_management invite create
    docker exec -it rueckgrat_hub python -m app.hub_management invite create --email a@b.c --days 3 --max-uses 2
    docker exec -it rueckgrat_hub python -m app.hub_management invite create --nsfw on
    docker exec -it rueckgrat_hub python -m app.hub_management invite list
    docker exec -it rueckgrat_hub python -m app.hub_management invite remove 4
    docker exec -it rueckgrat_hub python -m app.hub_management invite modify 4 --nsfw on
    docker exec -it rueckgrat_hub python -m app.hub_management invite modify 4 --nsfw          (asks: on or off?)
    docker exec -it rueckgrat_hub python -m app.hub_management user create martin
    docker exec -it rueckgrat_hub python -m app.hub_management user create martin --password secret --nsfw
    docker exec -it rueckgrat_hub python -m app.hub_management user list
    docker exec -it rueckgrat_hub python -m app.hub_management user modify martin --nsfw off
    docker exec -it rueckgrat_hub python -m app.hub_management user modify martin --nsfw       (asks: on or off?)
    docker exec -it rueckgrat_hub python -m app.hub_management companion list
    docker exec -it rueckgrat_hub python -m app.hub_management companion list --user martin
    docker exec -it rueckgrat_hub python -m app.hub_management companion status 31
    docker exec -it rueckgrat_hub python -m app.hub_management companion status 31 --log 50 --json
    docker exec -it rueckgrat_hub python -m app.hub_management maintenance status
    docker exec -it rueckgrat_hub python -m app.hub_management maintenance run
    docker exec -it rueckgrat_hub python -m app.hub_management maintenance run --job summaries --all

Whoever can run docker on the host is trusted as admin.
"""
import argparse
import json
from datetime import datetime, timezone

from argon2 import PasswordHasher

from app.utils.db import ChatDB

DB_PATH = "/hub/db/chat.db"
# placeholder until the real domain is known
SIGNUP_URL = "https://rickratz.com/?invite={token}"

def print_invites(invites):
    GRAY_BG = "\033[48;5;236m"
    RESET = "\033[0m"

    header = f"{'ID':<5} {'BY':<12} {'EMAIL':<28} {'USES':<6} {'EXPIRES (UTC)':<17} {'CONTENT':<8} {'STATUS'}"
    print()
    print(f"{GRAY_BG}{header:<100}{RESET}")

    if not invites:
        print("No invites")
        return

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for i, invite in enumerate(invites):
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
        bg = GRAY_BG if i % 2 else ""
        line = f"{str(invite['id']):<5} {invite['created_by'] or '-':<12} {email:<28} {uses:<6} {expires:<17} {content:<8} {status}"
        print(f"{bg}{line:<100}{RESET}")


def print_users(users):
    GRAY_BG = "\033[48;5;236m"
    RESET = "\033[0m"

    header = f"{'ID':<5} {'USER':<20} {'CONTENT':<8} {'CREATED (UTC)'}"
    print()
    print(f"{GRAY_BG}{header:<100}{RESET}")

    if not users:
        print("No users")
        return

    for i, user in enumerate(users):
        content = "NSFW" if user["nsfw_allowed"] else "SFW"
        created = (user["created_at"] or "")[:16]
        bg = GRAY_BG if i % 2 else ""
        line = f"{str(user['id']):<5} {user['username']:<20} {content:<8} {created}"
        print(f"{bg}{line:<100}{RESET}")


def companion_now(db):
    """the hub's companion clock, real time"""
    from app.companion import clock
    return clock.now(), "real time"


def companion_status(db, contact, log_entries):
    """everything about one companion as a dict, times in the user's timezone"""
    from app.companion import clock, companion_job as cj
    from app.companion.scheduler import CompanionScheduler
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
        "cutoff": CompanionScheduler(db, None, None, None).cutoff(contact_id, tz, now).astimezone(tz).strftime("%a %d %H:%M") if now else None,
        "messages_today": db.count_companion_messages(contact_id, clock.local_day(now.astimezone(tz))[0]) if now else None,
        "limits": f"{cj.MAX_MESSAGES_PER_DAY}/day, {cj.MIN_HOURS_BETWEEN_MESSAGES}h apart, quiet {cj.QUIET_HOURS[0]}-{cj.QUIET_HOURS[1]}h, "
                  f"not within {cj.USER_ACTIVE_MINUTES} min of the user writing",
        "calendar": [{"row": r["id"], "due": local(r["due_at"]), "kind": r["kind"], "note": r["note"], "daily": r["recurrence"] == "daily"}
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
    for r in s["calendar"] or [{"due": "", "kind": "nothing pending", "note": "", "daily": False}]:
        print(f"    {r['due']:<12} {r['kind']:<10} {'daily' if r['daily'] else '':<6}{r['note']}")
    print(f"  last {len(s['log'])} pass{'' if len(s['log']) == 1 else 'es'}")
    for e in s["log"]:
        due = f" (due {e['occurrence']})" if e["occurrence"] != e["at"] else ""
        print(f"    {e['at']} {e['kind']} #{e['row']} {e['note']!r}{due}")
        for key in ("missed", "reflection", "lookup", "plan", "thoughts", "message", "error"):
            if key == "plan" and (e.get("plan") or (e["kind"] == "planning" and "plan" in e)):
                for line in e["plan"] or ["empty plan"]:
                    print(f"        {'plan':<10} {line}")
            elif e.get(key):
                print(f"        {key:<10} {e[key]}")


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
        for key, value in task.status().items():
            print(f"    {key:<16} {value if value is not None else '-'}")


def maintenance_run(db, args):
    """runs the pending maintenance now, outside the window, one item at a time on this process.
    it does not see the hub's chats: it does not wait for replies being made"""
    import asyncio
    from app.jobs import JobQueue
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
    MaintenanceSweeper(db, JobQueue(max_parallel=1), tasks).sweep(user_id, None if args.all else sweeper.BATCH, [args.job] if args.job else None)
    maintenance_status(db)


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
        description="hub management: signup invites and users",
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
      --user      only this user's items""",
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

    args = parser.parse_args()
    if args.noun == "maintenance" and args.action == "status":
        maintenance_status(ChatDB.read_only(DB_PATH))
        return
    if args.noun == "companion":
        db = ChatDB.read_only(DB_PATH)
        if args.action == "list":
            rows = db.companion_contacts(user_name=args.user)
            print(f"\n{'ID':<5} {'USER':<16} {'CONTACT':<20} {'COMPANION':<10} {'PENDING':<8} LAST PASS (UTC)")
            for r in rows:
                print(f"{r['id']:<5} {r['username']:<16} {r['name'][:20]:<20} {'on' if r['companion'] else 'off':<10} {r['pending']:<8} {r['last_pass'] or '-'}")
            if not rows:
                print("No companions")
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

if __name__ == "__main__":
    main()
