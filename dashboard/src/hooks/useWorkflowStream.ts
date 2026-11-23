import { useEffect, useRef, useState } from "react";
import type { WorkflowState } from "../types";

export interface StreamEvent {
  event: string;
  job_id: string;
  state?: WorkflowState;
  progress_percentage?: number;
  message?: string;
  timestamp?: string;
}

export function useWorkflowStream(jobId: string | undefined) {
  const [isConnected, setIsConnected] = useState(false);
  const [lastEvent, setLastEvent] = useState<StreamEvent | null>(null);
  const socketRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!jobId) return;

    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const host = window.location.host;
    const wsUrl = `${protocol}//${host}/api/v1/ws/workflows/${jobId}`;

    const ws = new WebSocket(wsUrl);
    socketRef.current = ws;

    ws.onopen = () => {
      setIsConnected(true);
    };

    ws.onmessage = (event) => {
      try {
        const parsed: StreamEvent = JSON.parse(event.data);
        setLastEvent(parsed);
      } catch {
        // Plain text pong or other message
      }
    };

    ws.onclose = () => {
      setIsConnected(false);
    };

    ws.onerror = () => {
      setIsConnected(false);
    };

    // Heartbeat ping every 15s to keep connection alive
    const pingInterval = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send("ping");
      }
    }, 15000);

    return () => {
      clearInterval(pingInterval);
      ws.close();
    };
  }, [jobId]);

  return { isConnected, lastEvent };
}
