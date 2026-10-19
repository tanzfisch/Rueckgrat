"""
Admin tool for signup invites, run inside the hub container:

    docker exec -it rueckgrat_hub python -m app.invites create --by martin
    docker exec -it rueckgrat_hub python -m app.invites create --by martin --email a@b.c --days 3 --max-uses 2
    docker exec -it rueckgrat_hub python -m app.invites create --by martin --nsfw
    docker exec -it rueckgrat_hub python -m app.invites list
    docker exec -it rueckgrat_hub python -m app.invites remove 4

Whoever can run docker on the host is trusted as admin.
"""
import argparse
from datetime import datetime, timezone

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
        line = f"{str(invite['id']):<5} {invite['created_by']:<12} {email:<28} {uses:<6} {expires:<17} {content:<8} {status}"
        print(f"{bg}{line:<100}{RESET}")


def main():
    parser = argparse.ArgumentParser(
        prog="python -m app.invites",
        description="manage signup invites",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""commands:
  create --by NAME [--email EMAIL] [--days N] [--max-uses N] [--nsfw]
      --by        who creates the invite (required)
      --email     only this email may use the invite
      --days      days until expiry, 0 for never (default 7)
      --max-uses  how many signups the invite allows (default 1)
      --nsfw      the invited user may use NSFW settings (default off = SFW only)
  list            list all invites, 'email': None means not bound
  remove ID       delete an invite by its id (see list)""",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    create = sub.add_parser("create", help="create an invite and print its token")
    create.add_argument("--by", required=True, help="who creates the invite")
    create.add_argument("--email", default=None, help="only this email may use the invite")
    create.add_argument("--days", type=float, default=7, help="days until expiry, 0 for never (default 7)")
    create.add_argument("--max-uses", type=int, default=1, help="how many signups the invite allows (default 1)")
    create.add_argument("--nsfw", action="store_true", help="the invited user may use NSFW settings (default off = SFW only)")

    sub.add_parser("list", help="list invites")

    remove = sub.add_parser("remove", help="delete an invite")
    remove.add_argument("id", type=int, help="invite id as shown by list")

    args = parser.parse_args()
    db = ChatDB(DB_PATH)

    if args.cmd == "create":
        if args.max_uses < 1:
            parser.error("--max-uses must be at least 1")
        token = db.create_invite(args.by, args.email, args.days or None, args.max_uses, args.nsfw)
        print(f"created new token: {token}")
        print(f"signup url: {SIGNUP_URL.format(token=token)}")
    elif args.cmd == "list":
        print_invites(db.get_invites())
    elif args.cmd == "remove":
        print("removed" if db.remove_invite(args.id) else "not found")

if __name__ == "__main__":
    main()
