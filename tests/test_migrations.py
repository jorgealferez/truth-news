from sqlalchemy import create_engine, inspect

from truthnews.migrate import downgrade, upgrade
from truthnews.models import Base


def test_upgrade_matches_models_and_downgrade_is_clean(tmp_path):
    url = f"sqlite:///{tmp_path / 'm.db'}"
    upgrade(url)
    insp = inspect(create_engine(url))
    tables = set(insp.get_table_names()) - {"alembic_version"}
    assert tables == set(Base.metadata.tables)
    for name, table in Base.metadata.tables.items():
        assert {c["name"] for c in insp.get_columns(name)} == {c.name for c in table.columns}
    idx = {i["name"] for i in insp.get_indexes("article")}
    assert {
        "ix_article_category_published",
        "ix_article_country_published",
        "ix_article_outlet_published",
    } <= idx
    downgrade(url)
    assert set(inspect(create_engine(url)).get_table_names()) <= {"alembic_version"}
