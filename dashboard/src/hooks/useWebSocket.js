import { useState, useEffect, useRef, useCallback } from "react";

const API = import.meta.env.VITE_API_URL || `http://${window.location.host}`;

export function useWebSocket(onTick, timeframe) {
  const [connected, setConnected] = useState(false);
  const wsRef = useRef(null);
  const reconnectTimer = useRef(null);

  const connect = useCallback(() => {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const url = `${protocol}//${window.location.host}/ws?timeframe=${timeframe}`;

    try {
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        setConnected(true);
        console.log(`[WS][${timeframe}] Connected`);
      };

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);
          if (msg.type === "tick" && msg.data) {
            onTick(msg.data);
          }
        } catch {}
      };

      ws.onclose = () => {
        setConnected(false);
        console.log(`[WS][${timeframe}] Disconnected, retry in 5s...`);
        reconnectTimer.current = setTimeout(connect, 5000);
      };

      ws.onerror = () => {
        ws.close();
      };
    } catch {
      setConnected(false);
      reconnectTimer.current = setTimeout(connect, 5000);
    }
  }, [onTick, timeframe]);

  useEffect(() => {
    connect();
    return () => {
      clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
    };
  }, [connect]);

  return { connected };
}
