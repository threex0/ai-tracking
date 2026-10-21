from pathlib import Path

BASE = Path(__file__).resolve().parent

DATA_DIR = BASE / "data"
OUTPUT_DIR = BASE / "output"
REFERENCES_DIR = BASE / "references"
SITE_DIR = BASE / "site"

SOURCES_FILE = BASE / "sources.json"
ENV_FILE = BASE / ".env"

STATE_FILE = DATA_DIR / "state.json"
ITEMS_FILE = DATA_DIR / "items.json"

DIGEST_FILE = OUTPUT_DIR / "digest.md"
STORY_FILE = OUTPUT_DIR / "stories.md"
IDEAS_FILE = OUTPUT_DIR / "ideas.md"

DIGESTS_DIR = OUTPUT_DIR / "digests"
STORIES_DIR = OUTPUT_DIR / "stories"
IDEAS_DIR = OUTPUT_DIR / "ideas"

SITE_OUTPUT = OUTPUT_DIR / "site"
