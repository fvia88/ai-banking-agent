"""Render entry point: validate secrets, migrate/seed Neon, then serve one app."""
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT)]


def main():
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env.local', override=False)
    from sqlalchemy.engine import make_url
    from infra.shared_app import SharedSettings
    SharedSettings.from_environment()
    if not os.getenv('GROQ_API_KEY', '').strip():
        raise ValueError('Set GROQ_API_KEY in the hosting dashboard')
    if os.getenv('AGENT_PROVIDER', 'groq') != 'groq':
        raise ValueError('The hosted live demo requires AGENT_PROVIDER=groq')
    os.environ.setdefault('AGENT_PROVIDER', 'groq')
    for flag in ('USE_MOCK_AGENT', 'USE_MOCK_SECURITY', 'USE_MOCK_SUBSCRIPTIONS'):
        if os.getenv(flag, 'false').lower() != 'false':
            raise ValueError('Hosted demo requires the real agent, security and subscription adapters')
        os.environ.setdefault(flag, 'false')
    database = os.getenv('DATABASE_URL', '')
    try:
        parsed = make_url(database)
        valid = (parsed.drivername in {'postgresql', 'postgresql+psycopg2'}
                 and parsed.query.get('sslmode') in {'require', 'verify-ca', 'verify-full'})
    except Exception:
        valid = False
    if not valid:
        raise ValueError('Set DATABASE_URL to the Neon PostgreSQL URL with sslmode=require')
    port = int(os.getenv('PORT', '10000'))
    if not 1 <= port <= 65535:
        raise ValueError('Invalid PORT')
    from app.db.seed import seed_database
    import uvicorn
    seed_database()  # Migrates and seeds only when needed; never resets a demo.
    uvicorn.run('infra.shared_app:create_app', factory=True, host='0.0.0.0', port=port,
                workers=1, server_header=False)


if __name__ == '__main__':
    main()
