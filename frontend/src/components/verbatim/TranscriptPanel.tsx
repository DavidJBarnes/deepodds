import { useEffect, useRef } from 'react';
import type { StreamOut, TranscriptEvent } from '@/types/verbatim';
import { Badge } from './ui';

export interface TranscriptLine {
  key: string;
  event: TranscriptEvent;
  receivedAt: number;
}

interface Props {
  stream: StreamOut;
  lines: TranscriptLine[];
}

export function TranscriptPanel({ stream, lines }: Props) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const pinnedRef = useRef(true);

  // Auto-scroll to bottom unless the user scrolled up.
  useEffect(() => {
    const el = scrollRef.current;
    if (el && pinnedRef.current) {
      el.scrollTop = el.scrollHeight;
    }
  }, [lines]);

  const onScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    pinnedRef.current =
      el.scrollHeight - el.scrollTop - el.clientHeight < 48;
  };

  return (
    <div className="flex h-full flex-col rounded-lg border border-slate-800 bg-slate-900/60">
      <div className="flex items-center justify-between border-b border-slate-800 px-3 py-2">
        <div className="flex items-center gap-2 truncate">
          <Badge
            color={
              stream.status === 'live'
                ? 'green'
                : stream.status === 'armed'
                  ? 'blue'
                  : stream.status === 'dead'
                    ? 'red'
                    : 'slate'
            }
          >
            {stream.status}
          </Badge>
          <span className="truncate text-sm font-medium text-slate-200">
            {stream.label || stream.url}
          </span>
        </div>
        {stream.expected_speaker && (
          <span className="text-xs text-slate-500">
            expects {stream.expected_speaker}
          </span>
        )}
      </div>

      <div
        ref={scrollRef}
        onScroll={onScroll}
        className="scroll-thin flex-1 space-y-1.5 overflow-y-auto px-3 py-2 text-sm leading-relaxed"
      >
        {lines.length === 0 && (
          <div className="py-6 text-center text-xs text-slate-600">
            waiting for transcript…
          </div>
        )}
        {lines.map((line) => (
          <TranscriptRow key={line.key} line={line} />
        ))}
      </div>
    </div>
  );
}

function TranscriptRow({ line }: { line: TranscriptLine }) {
  const { event } = line;
  const speaker = event.speaker;
  return (
    <div className="flex gap-2">
      {speaker != null && (
        <span className="mt-0.5 shrink-0">
          <Badge color="purple">{speaker}</Badge>
        </span>
      )}
      <p className="text-slate-200">
        {event.words && event.words.length > 0 ? (
          event.words.map((w, i) => (
            <span
              key={i}
              title={`${w.start.toFixed(2)}–${w.end.toFixed(2)}s`}
              className="hover:text-emerald-300"
            >
              {w.text}
              {i < event.words!.length - 1 ? ' ' : ''}
            </span>
          ))
        ) : (
          <span>{event.text}</span>
        )}
      </p>
    </div>
  );
}
