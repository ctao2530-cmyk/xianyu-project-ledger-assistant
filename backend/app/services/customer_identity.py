from __future__ import annotations

from sqlalchemy import select

from ..models import (
    Conversation,
    CustomerChannelIdentity,
    RequirementCase,
    RequirementCaseSource,
    SalesLead,
)


def linked_customer_ids(session, conversation: Conversation) -> set[str]:
    """Resolve every durable customer relationship for one conversation."""

    identity = session.scalar(
        select(CustomerChannelIdentity).where(
            CustomerChannelIdentity.channel == conversation.channel,
            CustomerChannelIdentity.external_customer_id == conversation.customer_id,
        )
    )
    lead = session.scalar(
        select(SalesLead).where(SalesLead.conversation_id == conversation.id)
    )
    case_customer_ids = session.scalars(
        select(RequirementCase.customer_id)
        .join(RequirementCaseSource, RequirementCaseSource.case_id == RequirementCase.id)
        .where(RequirementCaseSource.conversation_id == conversation.id)
        .distinct()
    ).all()
    return {
        str(customer_id)
        for customer_id in (
            identity.customer_id if identity else None,
            lead.customer_id if lead else None,
            *case_customer_ids,
        )
        if customer_id
    }
