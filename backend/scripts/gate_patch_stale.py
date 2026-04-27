from sqlalchemy import text

from app.core.db import engine


def main() -> None:
    sid = "a3f62727-05f7-4c05-ac8b-7c637ef83264"
    with engine.begin() as c:
        c.execute(text("update sessions set review_timeout_hours=0 where id=:sid"), {"sid": sid})
        c.execute(
            text(
                "update experiments set created_at=datetime('now','-2 hours') "
                "where session_id=:sid and status='awaiting_review'"
            ),
            {"sid": sid},
        )
    print("patched")


if __name__ == "__main__":
    main()

