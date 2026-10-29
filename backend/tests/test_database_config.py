"""Standard hosted Postgres URLs must use the repository's installed driver."""
import pytest
from app.config import Settings


@pytest.mark.parametrize('prefix', ['postgresql://', 'postgres://', 'postgresql+psycopg2://'])
def test_hosted_urls_select_psycopg2_without_changing_connection_details(prefix):
    suffix = 'demo:synthetic%40password@db.example/neondb?sslmode=require&channel_binding=require'
    config = Settings(DATABASE_URL=prefix + suffix, _env_file=None)
    assert config.DATABASE_URL == 'postgresql+psycopg2://' + suffix


def test_sqlite_configuration_is_unchanged():
    assert Settings(DATABASE_URL='sqlite:///demo.db', _env_file=None).DATABASE_URL == 'sqlite:///demo.db'
