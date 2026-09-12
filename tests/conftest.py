import pytest

from resume_maker.catalog import Catalog
from resume_maker.db import Database


@pytest.fixture
def catalog(tmp_path):
    return Catalog(Database(tmp_path / "data" / "resume.db"))


@pytest.fixture
def project(catalog, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "README.md").write_text(
        "# Example\nA project for document processing.\n", encoding="utf-8"
    )
    return catalog.create_project("Example", [str(source)])


def experience(title="Example"):
    return {
        "title": title,
        "period": "",
        "role": "",
        "stack": ["Python"],
        "description": "Document processing",
        "highlights": [
            {"id": "one", "title": "Parser", "text": "Parse documents", "evidence": []},
            {"id": "two", "title": "Export", "text": "Export Word", "evidence": []},
        ],
    }


@pytest.fixture
def populated(catalog, project):
    base = project["head_revision"]
    catalog.put_draft(project["id"], base, "experience", experience(), 0)
    return catalog.save_field(project["id"], base, "experience", base)
