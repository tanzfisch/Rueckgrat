from app.utils import ModelRegistry
from pathlib import Path
import argparse
import sys


def format_size(size_bytes: float) -> str:
    value = size_bytes / (1024 ** 2)
    for unit in ("MB", "GB", "TB", "PB"):
        if value < 1024 or unit == "PB":
            return f"{value:.2f} {unit}"
        value /= 1024


def print_list(registry, type: None, verbose: bool):
    GRAY_BG = "\033[48;5;236m"
    RESET = "\033[0m"

    header = f"{'NAME':<80} {'INST.':<6} {'SIZE':<10}  {'AVAIL.':<10} "
    print()
    print(f"{GRAY_BG}{header:<130}{RESET}")

    models = registry.get_models()
    for i, model_name in enumerate(models):
        model = registry.get_model(model_name)
        if type != "" and type != model["type"]:
            continue

        installed = registry.is_installed(model_name)
        bg = GRAY_BG if i % 2 else ""

        if verbose:
            status = "✅" if installed else "⚫"
            size = format_size(registry.get_size(model_name)) if installed else ""
            if not installed:
                local = registry.find_local(model_name) or ""
            else:
                local = ""
            line = f"{model_name:<80} {status:<5} {size:<10} {local:<10}"
        else:
            line = model_name

        print(f"{bg}{line:<129}{RESET}")


def _service_names(node):
    names = []
    for svc in node.get("services") or []:
        names.append(svc.get("name") or svc.get("type") or "-")
    for svc in node.get("modules") or []:
        names.append(svc.get("name") or svc.get("type") or "-")
    return ", ".join(names) if names else "-"


def print_nodes(registry):
    GRAY_BG = "\033[48;5;236m"
    RESET = "\033[0m"

    header = f"{'ADDR':<18} {'PORT':<8} {'STATUS':<10} {'SERVICES'}"
    print()
    print(f"{GRAY_BG}{header:<100}{RESET}")

    nodes = registry.get_nodes()
    if not nodes:
        print("No nodes in infrastructure config.")
        return

    for i, node in enumerate(nodes):
        addr = node.get("addr", "-")
        port = node.get("port", "-")
        status = "online" if registry.is_node_online(node) else "offline"
        services = _service_names(node)
        bg = GRAY_BG if i % 2 else ""
        line = f"{str(addr):<18} {str(port):<8} {status:<10} {services}"
        print(f"{bg}{line:<100}{RESET}")


def main():
    parser = argparse.ArgumentParser(
        description="Model Registry CLI"
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    install = subparsers.add_parser("install", help="Fetch a model by name")
    install.add_argument("name", type=str, help="name of the model to install")
    install.add_argument("--source", type=str, help="custom source URL")
    install.add_argument("--force", action="store_true", help="forces download and replaces existing files")

    list_cmd = subparsers.add_parser("list", help="List models register")
    list_cmd.add_argument("--verbose", "-v", action="store_true", help="more verbose output")
    list_cmd.add_argument("--type", "-t", type=str, default="", help="only show models of given type (ie. llm, image, tts, stt)")

    subparsers.add_parser("nodes", help="List infrastructure nodes and online status")

    args = parser.parse_args()

    registry = ModelRegistry()

    if args.command == "install":
        model = registry.install_model(args.name, args.source, args.force)
        if not model:
            print("Error: failed to install model")
            sys.exit(1)

        print(f"Model \"{args.name}\" installed.")

    elif args.command == "list":
        print_list(registry, args.type, args.verbose)

    elif args.command == "nodes":
        print_nodes(registry)

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()