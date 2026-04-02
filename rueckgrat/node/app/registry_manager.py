from app.utils import ModelRegistry
from pathlib import Path
import argparse
import sys

def main():
    parser = argparse.ArgumentParser(
        description="Model Registry CLI"
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # fetch command
    install = subparsers.add_parser("install", help="Fetch a model by name")
    install.add_argument("name", type=str,help="name of the model to install")
    install.add_argument("--source", type=str, help="custom source URL")
    install.add_argument("--force", action="store_true", help="forces download and replaces existing files")

    list = subparsers.add_parser("list", help="List models register")
    list.add_argument("--verbose", "-v", action="store_true", help="more verbose output")
    list.add_argument("--type", "-t", type=str, default="", help="only show models of given type (ie. llm, image, tts, stt)")

    startup_parameters_parser = subparsers.add_parser("startup_parameters", help="List startup parameters for this model")
    startup_parameters_parser.add_argument("name", type=str, help="name of the model to return data from")

    args = parser.parse_args()

    registry = ModelRegistry("/node/models")

    if args.command == "install":
        model_cfg = registry.get_model_cfg(args.name)
        if not model_cfg:
            print(f"Error: model \"{args.name}\" not registered")
            sys.exit(1)

        model_cfg = registry.install_model(args.name, args.source, args.force)
        if not model_cfg:
            print("Error: failed to install model")
            sys.exit(1)

        print(f"Model \"{args.name}\" installed.")

    elif args.command == "list":
        data = registry.get_registry()
        for key, model_cfg in data.items():
            if args.type != "" and args.type != model_cfg["type"]:
                continue

            installed = registry.check_model_files(model_cfg)

            if args.verbose:
                if installed:
                    size_gb = registry.get_model_size(model_cfg)
                    print(f"{key:<100} - installed ({size_gb:.4f} GB)")
                else:
                    print(f"{key:<100} - NOT installed")
            else:
                print(key)
    
    elif args.command == "startup_parameters":
        model_cfg = registry.get_model_cfg(args.name)
        if not model_cfg:
            print(f"Error: model \"{args.name}\" not registered")
            sys.exit(1)

        print(model_cfg['startup_parameters'])

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()