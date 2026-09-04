"""Render site/index.html (full page + watchlist editor) and the email HTML
(brief content only) from the day's brief and current watchlist."""
import os
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "templates"
SITE = ROOT / "site"

_env = Environment(loader=FileSystemLoader(TEMPLATES))


def _split_by_flag(items):
    high = [i for i in items if i["flag"] == "HIGH"]
    medium = [i for i in items if i["flag"] == "MEDIUM"]
    quiet = [i for i in items if i["flag"] == "QUIET"]
    return high, medium, quiet


def _gh_owner_repo():
    # GITHUB_REPOSITORY is set automatically inside GitHub Actions as "owner/repo".
    repo = os.environ.get("GITHUB_REPOSITORY", "your-username/Morning-Brief")
    owner, _, name = repo.partition("/")
    return owner, name or "Morning-Brief"


def render_site(date_iso, brief, tickers):
    template = _env.get_template("brief_template.html")
    owner, repo = _gh_owner_repo()
    high, medium, quiet = _split_by_flag(brief["items"])
    html = template.render(
        date=date_iso, high=high, medium=medium, quiet=quiet,
        tickers=tickers, gh_owner=owner, gh_repo=repo,
    )
    SITE.mkdir(exist_ok=True)
    (SITE / "index.html").write_text(html, encoding="utf-8")
    return html


def render_email(date_iso, brief):
    template = _env.get_template("email_template.html")
    owner, repo = _gh_owner_repo()
    high, medium, quiet = _split_by_flag(brief["items"])
    return template.render(
        date=date_iso, high=high, medium=medium, quiet=quiet,
        gh_owner=owner, gh_repo=repo,
    )
