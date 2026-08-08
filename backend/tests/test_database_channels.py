from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from backend.app.channels.base import ChannelMessage
from backend.app.database import Database, create_database_engine
from backend.app.models import Conversation, Message
from backend.app.services.repository import ingest_message


def test_existing_sqlite_database_gets_additive_channel_migration(tmp_path) -> None:
    url = f"sqlite:///{tmp_path / 'legacy.db'}"
    engine = create_database_engine(url)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE conversations ("
            "id INTEGER PRIMARY KEY, external_id VARCHAR(128) NOT NULL UNIQUE, "
            "customer_id VARCHAR(128) NOT NULL, customer_name VARCHAR(255) NOT NULL, "
            "item_id INTEGER, unread_count INTEGER NOT NULL, "
            "last_message_at DATETIME NOT NULL, created_at DATETIME NOT NULL, "
            "updated_at DATETIME NOT NULL)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE messages ("
            "id INTEGER PRIMARY KEY, external_id VARCHAR(255) NOT NULL UNIQUE, "
            "conversation_id INTEGER NOT NULL, sender_id VARCHAR(128) NOT NULL, "
            "sender_name VARCHAR(255) NOT NULL, direction VARCHAR(16) NOT NULL, "
            "message_type VARCHAR(32) NOT NULL, content TEXT NOT NULL, "
            "status VARCHAR(32) NOT NULL, risk_flags_json TEXT NOT NULL, "
            "client_send_uuid VARCHAR(128), received_at DATETIME NOT NULL, "
            "created_at DATETIME NOT NULL)"
        )
        connection.exec_driver_sql(
            "INSERT INTO conversations VALUES "
            "(1, 'legacy-conversation', 'legacy-buyer', '旧客户', NULL, 1, "
            "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )
        connection.exec_driver_sql(
            "INSERT INTO messages VALUES "
            "(1, 'legacy-message', 1, 'legacy-buyer', '旧客户', 'inbound', "
            "'text', '旧消息', 'new', '[]', NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )
    engine.dispose()

    database = Database(url)
    database.create_all()

    with database.session() as session:
        conversation = session.scalar(select(Conversation))
        message = session.scalar(select(Message))
        assert conversation is not None and conversation.channel == "xianyu"
        assert message is not None and message.channel == "xianyu"
        assert message.platform_message_id == "legacy-message"


def test_same_platform_message_id_is_isolated_by_channel(tmp_path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'channel-identity.db'}")
    database.create_all()
    timestamp = datetime.now(timezone.utc)
    xianyu = ChannelMessage(
        channel="xianyu",
        platform_message_id="shared-1001",
        external_id="shared-1001",
        conversation_id="xianyu-conversation",
        sender_id="xianyu-user",
        sender_name="闲鱼客户",
        content="闲鱼消息",
        message_type="text",
        received_at=timestamp,
    )
    wechat = ChannelMessage(
        channel="wechat",
        platform_message_id="shared-1001",
        external_id="wechat:shared-1001",
        conversation_id="wechat:wechat-user",
        sender_id="wechat-user",
        sender_name="微信客户",
        content="微信消息",
        message_type="text",
        received_at=timestamp,
    )

    with database.session() as session:
        assert ingest_message(session, xianyu, [], None).is_new
    with database.session() as session:
        assert ingest_message(session, wechat, [], None, source="wechat_webhook").is_new

    with database.session() as session:
        messages = list(session.scalars(select(Message).order_by(Message.channel)))
        assert {(message.channel, message.platform_message_id) for message in messages} == {
            ("xianyu", "shared-1001"),
            ("wechat", "shared-1001"),
        }
