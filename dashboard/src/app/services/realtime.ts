import { DestroyRef, Injectable, inject, signal } from '@angular/core';
import type {
  ActivityEntry,
  ConnectionState,
  Stats,
  Topic,
  TriageItem,
} from '../models/triage';

interface ServerMessage {
  topic: Topic;
  type: 'snapshot' | 'updated' | 'claimed' | 'released' | 'appended';
  payload: unknown;
}

const HEARTBEAT_MS = 30_000;
const MAX_BACKOFF_MS = 30_000;

/**
 * Single WebSocket client, signal-driven.
 *
 * - Snapshot-on-subscribe: every subscribe (including reconnects) receives a
 *   fresh snapshot per topic, so the UI never needs a REST round-trip.
 * - Heartbeat pings every 30s so the connection survives idle proxies.
 * - Exponential backoff with jitter on reconnect.
 * - Cleans up on DestroyRef (HMR-safe).
 */
@Injectable({ providedIn: 'root' })
export class Realtime {
  private readonly destroyRef = inject(DestroyRef);
  private readonly url = this.resolveUrl();
  private readonly topics: Topic[] = ['items', 'stats', 'activity'];

  private readonly _items = signal<TriageItem[] | undefined>(undefined);
  private readonly _stats = signal<Stats | undefined>(undefined);
  private readonly _activity = signal<ActivityEntry[] | undefined>(undefined);
  private readonly _state = signal<ConnectionState>('connecting');
  private readonly _lastUpdated = signal<number | null>(null);

  readonly items = this._items.asReadonly();
  readonly stats = this._stats.asReadonly();
  readonly activity = this._activity.asReadonly();
  readonly state = this._state.asReadonly();
  readonly lastUpdated = this._lastUpdated.asReadonly();

  private socket: WebSocket | null = null;
  private reconnectAttempts = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  private disposed = false;

  constructor() {
    this.connect();
    this.destroyRef.onDestroy(() => {
      this.disposed = true;
      this.clearTimers();
      this.socket?.close();
      this.socket = null;
    });
  }

  private resolveUrl(): string {
    if (typeof window === 'undefined') return '';
    const w = window as unknown as { __WS_URL__?: string };
    if (w.__WS_URL__) return w.__WS_URL__;
    // Angular's ng serve runs on :4200 and can't easily proxy WS — in dev
    // we hit the Bun server directly on :7800.
    if (window.location.port === '4200') {
      return 'ws://localhost:7800/ws';
    }
    // Prod: WS is same-origin (bun serves both the dashboard and /ws).
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${proto}//${window.location.host}/ws`;
  }

  private connect() {
    if (this.disposed) return;
    this._state.set('connecting');
    const ws = new WebSocket(this.url);
    this.socket = ws;

    ws.addEventListener('open', () => {
      if (this.disposed) {
        ws.close();
        return;
      }
      this.reconnectAttempts = 0;
      this._state.set('open');
      ws.send(JSON.stringify({ subscribe: this.topics }));
      this.startHeartbeat();
    });

    ws.addEventListener('message', (ev) => {
      try {
        const msg = JSON.parse(ev.data) as ServerMessage;
        this.apply(msg);
        this._lastUpdated.set(Date.now());
      } catch {
        // ignore malformed frames
      }
    });

    ws.addEventListener('close', () => {
      this._state.set('closed');
      this.stopHeartbeat();
      this.scheduleReconnect();
    });

    ws.addEventListener('error', () => {
      ws.close();
    });
  }

  private apply(msg: ServerMessage) {
    switch (msg.topic) {
      case 'items':
        if (msg.type === 'snapshot') this._items.set(msg.payload as TriageItem[]);
        break;
      case 'stats':
        if (msg.type === 'snapshot') this._stats.set(msg.payload as Stats);
        break;
      case 'activity':
        if (msg.type === 'snapshot') this._activity.set(msg.payload as ActivityEntry[]);
        break;
      case 'claims':
        // Reserved for M2 claim/release deltas.
        break;
    }
  }

  private startHeartbeat() {
    this.stopHeartbeat();
    this.heartbeatTimer = setInterval(() => {
      if (this.socket?.readyState === WebSocket.OPEN) {
        // Empty ping keeps idle-timeout proxies happy; server ignores it.
        this.socket.send(JSON.stringify({ ping: Date.now() }));
      }
    }, HEARTBEAT_MS);
  }

  private stopHeartbeat() {
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
  }

  private scheduleReconnect() {
    if (this.disposed || this.reconnectTimer) return;
    const base = Math.min(1000 * 2 ** this.reconnectAttempts, MAX_BACKOFF_MS);
    // Full jitter: [0, base)
    const delay = Math.random() * base;
    this.reconnectAttempts += 1;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, delay);
  }

  private clearTimers() {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.stopHeartbeat();
  }
}
