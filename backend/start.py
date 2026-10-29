"""Run from repo root: python backend/start.py [--reload] [--port 8000]."""
import argparse
from pathlib import Path
import sys

# Works without requiring PYTHONPATH setup in a local shell.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))


def main():
    parser = argparse.ArgumentParser(description="Migrate, seed if empty, then start the backend")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    # Neon CLI writes this private file for local development. Hosting/terminal
    # environment variables take precedence; Docker excludes the file entirely.
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / '.env.local', override=False)

    from app.db.seed import seed_database
    import uvicorn

    # A migration/seed exception exits before Uvicorn can serve requests.
    seed_database()
    uvicorn.run("app.main:app", host=args.host, port=args.port, reload=args.reload,
                reload_dirs=[str(Path(__file__).resolve().parent)] if args.reload else None)


if __name__ == "__main__":
    main()
