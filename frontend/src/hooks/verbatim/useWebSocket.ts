import { useCallback, useEffect, useRef, useState } from 'react';
import type { WsMessage } from '@/types/verbatim';

export type WsStatus = 'connecting' | 'open' | 'closed';

interface UseWebSocketResult {
  status: WsStatus;
  /** The most recent message received (any type). */
  lastMessage: WsMessage | null;
  /** Send a text keepalive / arbitrary payload. */
  send: (data: string) => void;
}

/**
 * Auto-reconnecting WebSocket hook with exponential backoff.
 *
 * `onMessage` is invoked for every parsed message. It is stored in a ref so
 * that changing the handler does not tear down the socket.
 */
export function useWebSocket(
  path: string,
  onMessage?: (msg: WsMessage) => void,
): UseWebSocketResult {
  const [status, setStatus] = useState<WsStatus>('connecting');
  const [lastMessage, setLastMessage] = useState<WsMessage | null>(null);

  const socketRef = useRef<WebSocket | null>(null);
  const handlerRef = useRef(onMessage);
  const retryRef = useRef(0);
  const timerRef = useRef<number | null>(null);
  const closedRef = useRef(false);

  handlerRef.current = onMessage;

  const connect = useCallback(() => {
    if (closedRef.current) return;
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
    const url = `${proto}://${window.location.host}${path}`;
    setStatus('connecting');

    let ws: WebSocket;
    try {
      ws = new WebSocket(url);
    } catch {
      scheduleReconnect();
      return;
    }
    socketRef.current = ws;

    ws.onopen = () => {
      retryRef.current = 0;
      setStatus('open');
    };

    ws.onmessage = (event: MessageEvent<string>) => {
      let parsed: WsMessage | null = null;
      try {
        parsed = JSON.parse(event.data) as WsMessage;
      } catch {
        return; // ignore non-JSON (e.g. text keepalives)
      }
      if (!parsed || typeof parsed.type !== 'string') return;
      setLastMessage(parsed);
      handlerRef.current?.(parsed);
    };

    ws.onclose = () => {
      setStatus('closed');
      scheduleReconnect();
    };

    ws.onerror = () => {
      // onclose will follow and handle reconnection.
      ws.close();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path]);

  const scheduleReconnect = useCallback(() => {
    if (closedRef.current) return;
    if (timerRef.current != null) return;
    const attempt = retryRef.current;
    const delay = Math.min(1000 * 2 ** attempt, 15000);
    retryRef.current = attempt + 1;
    timerRef.current = window.setTimeout(() => {
      timerRef.current = null;
      connect();
    }, delay);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connect]);

  useEffect(() => {
    closedRef.current = false;
    connect();
    return () => {
      closedRef.current = true;
      if (timerRef.current != null) {
        window.clearTimeout(timerRef.current);
        timerRef.current = null;
      }
      socketRef.current?.close();
      socketRef.current = null;
    };
  }, [connect]);

  const send = useCallback((data: string) => {
    const ws = socketRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(data);
    }
  }, []);

  return { status, lastMessage, send };
}
