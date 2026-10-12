"""Start a fresh, isolated native-browser demo without changing existing companies."""

from __future__ import annotations

import argparse
import multiprocessing
import os
import socket
import tempfile
from pathlib import Path

from dotenv import load_dotenv


def serve_company(root: str, port: int, seed: int = 7) -> None:
    import uvicorn

    from precedent.apps.server import create_app

    uvicorn.run(create_app(seed, Path(root)), host="127.0.0.1", port=port, log_level="warning")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8009)
    parser.add_argument("--apps-port", type=int, default=8116)
    parser.add_argument("--world-root", type=Path)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--reuse", action="store_true", help="Restart the same retained company")
    args = parser.parse_args()
    if args.reuse and not args.world_root:
        parser.error("--reuse needs --world-root")
    if args.port == args.apps_port:
        parser.error("Console and company need separate ports.")
    for port in (args.port, args.apps_port):
        with socket.socket() as sock:
            # Match uvicorn: a recently closed demo's TIME_WAIT sockets do not occupy the port.
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                parser.error(f"Port {port} is occupied. Choose another port.")
    load_dotenv()
    if os.getenv("PRECEDENT_SCENARIO_TOKEN", "change-me") == "change-me":
        parser.error("Run make setup first to create the local scenario token.")
    import uvicorn

    from precedent.console.server import create_app
    from precedent.world.generator import generate

    root = (
        str(args.world_root.resolve())
        if args.world_root
        else tempfile.mkdtemp(prefix="precedent-demo-")
    )
    if args.reuse:
        if not (Path(root) / str(args.seed) / "world.db").exists():
            parser.error("Retained company not found")
    else:
        if (Path(root) / str(args.seed)).exists():
            parser.error("Company already exists; use --reuse to preserve it")
        generate("northwind", args.seed, Path(root) / str(args.seed))
    os.environ["PRECEDENT_CONSOLE_URL"] = f"http://localhost:{args.port}"
    apps_url = f"http://localhost:{args.apps_port}"
    process = multiprocessing.get_context("spawn").Process(
        target=serve_company, args=(root, args.apps_port, args.seed)
    )
    process.start()
    print(f"Fresh demo: http://localhost:{args.port}/", flush=True)
    print(f"Company: {apps_url} | Retained sandbox: {root}", flush=True)
    print("Choose a meeting or invoice task, then ‘Assign to Ava’.", flush=True)
    try:
        uvicorn.run(
            create_app(apps_url=apps_url, headed=True),
            host="127.0.0.1",
            port=args.port,
            log_level="warning",
        )
    finally:
        process.terminate()
        process.join(timeout=5)


if __name__ == "__main__":
    main()
