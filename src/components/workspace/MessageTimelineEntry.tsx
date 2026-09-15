import { UserCircle } from '@phosphor-icons/react';
import type { ReactNode } from 'react';
import { messageTime, showMessageTime } from './messageTimeline';

/** Presentation only: retain each exact platform timestamp; never modify message records. */
export function MessageTimelineEntry({ receivedAt, previousAt, direction, children, media, provenance, senderName }: {
  receivedAt: string; previousAt?: string; direction: string; children?: ReactNode; media?: ReactNode; provenance?: ReactNode; senderName?: string;
}) {
  const exact = messageTime(receivedAt, true);
  return <>
    {showMessageTime(receivedAt, previousAt) && <time className="message-time-divider" dateTime={receivedAt}>{messageTime(receivedAt)}</time>}
    <article className={`chat-message ${direction === 'outbound' ? 'outbound' : 'inbound'}`} data-message-time={receivedAt}>
      <time className="sr-only" dateTime={receivedAt}>消息时间（北京时间）：{exact}</time>
      {senderName && <div className="reference-message-sender"><UserCircle size={36} weight="duotone"/><span>{senderName}</span><time dateTime={receivedAt}>{messageTime(receivedAt).split(' ').at(-1)}</time></div>}
      {provenance}
      {children && <div className="chat-message-bubble" title={`消息时间（北京时间）：${exact}`}>
        {children}
      </div>}
      {media && <div className="chat-message-media" title={`消息时间（北京时间）：${exact}`}>{media}</div>}
    </article>
  </>;
}
