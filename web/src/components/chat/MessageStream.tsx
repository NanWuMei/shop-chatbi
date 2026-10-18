/** 消息流：按序渲染 ChatEntry（同一渲染器），自动滚底。 */
import { useEffect, useRef } from 'react';
import type { ChatEntry } from '../../store/chatStore';
import MessageEntry, { type RendererHandlers } from './MessageEntry';

export default function MessageStream({ entries, handlers }: { entries: ChatEntry[]; handlers: RendererHandlers }) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [entries.length]);

  let lastQuestion = '';
  return (
    <div className="message-stream" data-testid="message-stream">
      {entries.map((entry) => {
        if (entry.kind === 'user') lastQuestion = entry.question;
        return <MessageEntry key={entry.id} entry={entry} lastQuestion={lastQuestion} handlers={handlers} />;
      })}
      <div ref={bottomRef} />
    </div>
  );
}
