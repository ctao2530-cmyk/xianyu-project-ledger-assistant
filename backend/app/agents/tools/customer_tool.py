from __future__ import annotations

from typing import Any

from sqlalchemy import select

from ...database import Database
from ...models import (
    BusinessCustomer,
    BusinessProject,
    Conversation,
    CustomerChannelIdentity,
    Message,
    PaymentNode,
    SalesLead,
)


class CustomerHistoryTool:
    """Read-only customer history lookup used by the Sales Agent."""

    name = "customer_history"

    def __init__(self, database: Database, *, message_limit: int = 30) -> None:
        self.database = database
        self.message_limit = max(5, min(message_limit, 60))

    def run(self, conversation_id: int) -> dict[str, Any]:
        with self.database.session() as session:
            conversation = session.get(Conversation, conversation_id)
            if conversation is None:
                raise LookupError("会话不存在")

            identity = session.scalar(
                select(CustomerChannelIdentity).where(
                    CustomerChannelIdentity.channel == conversation.channel,
                    CustomerChannelIdentity.external_customer_id
                    == conversation.customer_id,
                )
            )
            lead = session.scalar(
                select(SalesLead).where(
                    SalesLead.conversation_id == conversation_id
                )
            )
            customer_id = (
                (identity.customer_id if identity else None)
                or (lead.customer_id if lead else None)
            )
            customer = (
                session.get(BusinessCustomer, customer_id) if customer_id else None
            )

            conversation_ids = {conversation_id}
            if customer_id:
                conversation_ids.update(
                    int(value)
                    for value in session.scalars(
                        select(CustomerChannelIdentity.conversation_id).where(
                            CustomerChannelIdentity.customer_id == customer_id,
                            CustomerChannelIdentity.conversation_id.is_not(None),
                        )
                    )
                    if value is not None
                )

            newest_messages = list(
                session.scalars(
                    select(Message)
                    .where(Message.conversation_id.in_(conversation_ids))
                    .order_by(Message.received_at.desc(), Message.id.desc())
                    .limit(self.message_limit)
                )
            )
            messages = [
                {
                    "message_id": message.id,
                    "conversation_id": message.conversation_id,
                    "direction": message.direction,
                    "content": message.content[:800],
                    "received_at": message.received_at.isoformat(),
                }
                for message in reversed(newest_messages)
            ]

            projects = (
                list(
                    session.scalars(
                        select(BusinessProject)
                        .where(BusinessProject.customer_id == customer_id)
                        .order_by(BusinessProject.created_at.desc())
                        .limit(12)
                    )
                )
                if customer_id
                else []
            )
            project_history = [
                {
                    "project_id": project.id,
                    "name": project.name,
                    "type": project.type,
                    "status": project.status,
                    "contract_amount": round(float(project.total_amount or 0), 2),
                    "estimated_hours": round(float(project.estimated_hours or 0), 1),
                }
                for project in projects
            ]
            confirmed_receipts = (
                list(
                    session.scalars(
                        select(PaymentNode.amount).where(
                            PaymentNode.customer_id == customer_id,
                            PaymentNode.status == "confirmed",
                        )
                    )
                )
                if customer_id
                else []
            )

            return {
                "customer": (
                    {
                        "customer_id": customer.id,
                        "name": customer.name,
                        "source": customer.source,
                        "follow_up_status": customer.follow_up_status,
                        "level": customer.level,
                    }
                    if customer
                    else None
                ),
                "channel_identity": {
                    "channel": conversation.channel,
                    "display_name": conversation.customer_name,
                    "is_linked_customer": bool(customer_id),
                },
                "message_history": messages,
                "project_history": project_history,
                "confirmed_revenue": round(
                    sum(float(amount or 0) for amount in confirmed_receipts), 2
                ),
                "message_count": len(messages),
                "project_count": len(project_history),
            }
