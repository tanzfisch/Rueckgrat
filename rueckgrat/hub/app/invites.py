"""
Admin tool for signup invites, run inside the hub container:

    docker exec -it rueckgrat_hub python -m app.invites create --by martin
    docker exec -it rueckgrat_hub python -m app.invites create --by martin --email a@b.c --days 3 --max-uses 2
    docker exec -it rueckgrat_hub python -m app.invites list
    docker exec -it rueckgrat_hub python -m app.invites remove 4

Whoever can run docker on the host is trusted as admin.
"""
import argparse

from app.utils.db import ChatDB

DB_PATH = "/hub/db/chat.db"

def main():
    parser = argparse.ArgumentParser(description="manage signup invites")
    sub = parser.add_subparsers(dest="cmd", required=True)

    create = sub.add_parser("create", help="create an invite and print its token")
    create.add_argument("--by", required=True, help="who creates the invite")
    create.add_argument("--email", default=None, help="only this email may use the invite")
    create.add_argument("--days", type=float, default=7, help="days until expiry, 0 for never (default 7)")
    create.add_argument("--max-uses", type=int, default=1, help="how many signups the invite allows (default 1)")

    sub.add_parser("list", help="list invites")

    remove = sub.add_parser("remove", help="delete an invite")
    remove.add_argument("id", type=int)

    args = parser.parse_args()
    db = ChatDB(DB_PATH)

    if args.cmd == "create":
        if args.max_uses < 1:
            parser.error("--max-uses must be at least 1")
        token = db.create_invite(args.by, args.email, args.days or None, args.max_uses)
        print(token)
    elif args.cmd == "list":
        for invite in db.get_invites():
            print(invite)
    elif args.cmd == "remove":
        print("removed" if db.remove_invite(args.id) else "not found")

if __name__ == "__main__":
    main()
