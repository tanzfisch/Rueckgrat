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

Whoever can run docker on the host is trusted as admin.
"""
import argparse
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
                  (takes effect on their next login)""",
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

    args = parser.parse_args()
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
