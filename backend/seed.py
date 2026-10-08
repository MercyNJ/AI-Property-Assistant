"""Create tables and load listings from the seed file."""

import argparse

from app.config import get_settings
from app.database import Base, SessionLocal, engine
from app.services.seeding import seed_properties


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--reset", action="store_true", help="delete existing listings first")
    args = parser.parse_args()

    settings = get_settings()
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        added = seed_properties(db, settings.seed_file, reset=args.reset)
    print(f"Added {added} listings." if added else "Database already has listings (use --reset to reload).")


if __name__ == "__main__":
    main()
