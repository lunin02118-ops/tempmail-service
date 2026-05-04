from __future__ import annotations

from sqlalchemy import create_engine, text

from app.config import AppSettings


def main() -> None:
    settings = AppSettings.from_env()
    engine = create_engine(settings.database_url)
    with engine.connect() as conn:
        rows = {
            "mailboxes_total": conn.execute(text("select count(*) from mailboxes")).scalar(),
            "mailboxes_public_active": conn.execute(
                text("select count(*) from mailboxes where visibility='public' and is_active=1")
            ).scalar(),
            "messages_total": conn.execute(text("select count(*) from messages")).scalar(),
            "messages_in_public": conn.execute(
                text(
                    "select count(*) from messages m "
                    "join mailboxes mb on mb.id=m.mailbox_id "
                    "where mb.visibility='public'"
                )
            ).scalar(),
            "ai_extractions_with_otp": conn.execute(
                text("select count(*) from ai_extractions where otp_code is not null and otp_code <> ''")
            ).scalar(),
        }
        for key, value in rows.items():
            print(f"{key}={value}")
        sample = conn.execute(
            text(
                "select m.id, m.subject, ae.otp_code, ae.sender_brand, mb.address, mb.visibility "
                "from messages m left join ai_extractions ae on ae.message_id=m.id "
                "join mailboxes mb on mb.id=m.mailbox_id "
                "where mb.visibility='public' "
                "order by m.received_at desc nulls last, m.id desc limit 5"
            )
        ).all()
        print("---sample---")
        for row in sample:
            print(row)


if __name__ == "__main__":
    main()
