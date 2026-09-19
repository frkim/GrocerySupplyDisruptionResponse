import { useEffect, useRef, useState } from 'react';
import type { LogEntry } from '../types';
import { formatClock } from '../lib/format';
import './EventLog.css';

interface EventLogProps {
  entries: LogEntry[];
}

export function EventLog({ entries }: EventLogProps) {
  const [pinned, setPinned] = useState(true);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!pinned) return;
    const node = scrollRef.current;
    if (node) node.scrollTop = node.scrollHeight;
  }, [entries, pinned]);

  return (
    <section className="card log">
      <div className="card__head">
        <h2 className="card__title">Event stream</h2>
        <div className="log__head-actions">
          <span className="chip">{entries.length}</span>
          <button
            type="button"
            className={`log__pin ${pinned ? 'log__pin--on' : ''}`}
            onClick={() => setPinned((value) => !value)}
            title={pinned ? 'Auto-scroll on' : 'Auto-scroll off'}
          >
            {pinned ? 'Following' : 'Paused'}
          </button>
        </div>
      </div>

      <div className="card__body card__body--flush log__scroll" ref={scrollRef}>
        {entries.length === 0 ? (
          <p className="empty">No events yet. Start a run to stream orchestration activity.</p>
        ) : (
          <ul className="log__list">
            {entries.map((entry) => (
              <li key={entry.id} className={`log__item log__item--${entry.level}`}>
                <span className="log__time mono">{formatClock(entry.at)}</span>
                <span className="log__label">{entry.label}</span>
                <span className="log__msg">{entry.message}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}

export default EventLog;
