/**
 * EventSource wrapper with token-on-URL auth + Page Visibility handbrake.
 *
 * Why token-on-URL: per Q3 (user decision), EventSource cannot send custom
 * headers. The backend accepts `?token=…` as a fallback for SSE routes
 * (godo-webctl/src/godo_webctl/auth.py::_extract_bearer). The backend
 * uvicorn access-log format strips `?token=…` from the URL line so the
 * token never lands in journald.
 *
 * Reconnect: EventSource has built-in reconnect after a transport drop.
 * We add a Page Visibility handbrake — when the tab is hidden, we close
 * the connection (no point burning the tracker's UDS); when it becomes
 * visible again, we reopen.
 *
 * Expired-token guard: before reopening (after a visibility change OR an
 * onerror event), we check `isExpired(token)`. If expired, we do NOT
 * reopen — the auth store will already have redirected the user to /login.
 */

import { isExpired } from './auth';

export interface SSEClientOptions {
  /** Path on the backend, e.g. "/api/last_pose/stream". */
  path: string;
  /** Returns the current JWT token (or null when unauthenticated). */
  getToken: () => string | null;
  /** Called on every successfully parsed `data: {…}` frame. */
  onMessage: (payload: unknown) => void;
  /** Called when the underlying EventSource raises an error. Optional. */
  onError?: (e: Event) => void;
  /**
   * If true, we attach the Page Visibility handbrake. Default true; tests
   * may set false to keep behaviour deterministic without tab simulation.
   */
  visibilityHandbrake?: boolean;
}

export class SSEClient {
  private _es: EventSource | null = null;
  private _opts: Required<Omit<SSEClientOptions, 'onError'>> & Pick<SSEClientOptions, 'onError'>;
  private _closed = false;
  private _visibilityHandler: (() => void) | null = null;

  constructor(opts: SSEClientOptions) {
    this._opts = {
      path: opts.path,
      getToken: opts.getToken,
      onMessage: opts.onMessage,
      onError: opts.onError,
      visibilityHandbrake: opts.visibilityHandbrake ?? true,
    };
  }

  /**
   * Open the EventSource. Idempotent — if already open, no-op.
   * Returns false when no valid token is available (caller should redirect
   * to /login); true on successful open.
   */
  open(): boolean {
    if (this._closed) return false;
    if (this._es) return true;
    const token = this._opts.getToken();
    if (!token || isExpired(token)) return false;

    const url = this._buildUrl(token);
    const es = new EventSource(url);
    es.onmessage = (ev: MessageEvent<string>) => {
      let payload: unknown;
      try {
        payload = JSON.parse(ev.data);
      } catch {
        // Drop malformed frames silently — backend wire is JSON only.
        return;
      }
      this._opts.onMessage(payload);
    };
    es.onerror = (ev: Event) => {
      // EventSource will auto-reconnect; we just expose the event for
      // callers that want to surface a "stale" indicator. If the token
      // expired meanwhile, suppress reconnect by closing.
      const t = this._opts.getToken();
      if (!t || isExpired(t)) {
        this.close();
      }
      this._opts.onError?.(ev);
    };
    this._es = es;

    if (this._opts.visibilityHandbrake && typeof document !== 'undefined') {
      this._visibilityHandler = () => {
        if (document.hidden) {
          this._closeEventSourceOnly();
        } else {
          this._reopen();
        }
      };
      document.addEventListener('visibilitychange', this._visibilityHandler);
    }
    return true;
  }

  /** Permanently close. After this, `open()` is a no-op. */
  close(): void {
    this._closed = true;
    this._closeEventSourceOnly();
    if (this._visibilityHandler && typeof document !== 'undefined') {
      document.removeEventListener('visibilitychange', this._visibilityHandler);
      this._visibilityHandler = null;
    }
  }

  /** Test hook — true while an underlying EventSource is live. */
  get isOpen(): boolean {
    return this._es !== null;
  }

  private _closeEventSourceOnly(): void {
    if (this._es) {
      this._es.close();
      this._es = null;
    }
  }

  private _reopen(): void {
    if (this._closed) return;
    this._closeEventSourceOnly();
    const token = this._opts.getToken();
    if (!token || isExpired(token)) return;
    // Re-enter open() but skip the visibility handler re-attach since it's
    // still bound from the original open().
    const url = this._buildUrl(token);
    const es = new EventSource(url);
    es.onmessage = (ev: MessageEvent<string>) => {
      let payload: unknown;
      try {
        payload = JSON.parse(ev.data);
      } catch {
        return;
      }
      this._opts.onMessage(payload);
    };
    es.onerror = (ev: Event) => {
      const t = this._opts.getToken();
      if (!t || isExpired(t)) {
        this.close();
      }
      this._opts.onError?.(ev);
    };
    this._es = es;
  }

  private _buildUrl(token: string): string {
    const u = new URL(this._opts.path, window.location.origin);
    u.searchParams.set('token', token);
    return u.toString();
  }
}
