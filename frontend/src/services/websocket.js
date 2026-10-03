/**
 * Dedicated WebSocket Service for KON Frontend.
 * Handles automatic connection, reconnection backoff, event dispatching, and command transmission.
 */

class KONWebSocketService {
  constructor() {
    this.ws = null;
    this.url = 'ws://127.0.0.1:8000/ws';
    this.isConnected = false;
    this.reconnectTimer = null;
    this.reconnectDelay = 2000;
    this.maxReconnectDelay = 10000;
    
    // Callbacks registered by the UI
    this.listeners = {
      state: [],
      telemetry: [],
      log: [],
      response: [],
      connection: [],
      transcription: [],
      confirmation: [],
      executing: [],
    };
  }

  connect() {
    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
      return;
    }

    try {
      this.ws = new WebSocket(this.url);

      this.ws.onopen = () => {
        this.isConnected = true;
        this.reconnectDelay = 2000;
        this._notify('connection', { connected: true, url: this.url });
      };

      this.ws.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data);
          this._handleIncomingMessage(payload);
        } catch (err) {
          console.error('[KON WebSocket] Failed to parse message:', err, event.data);
        }
      };

      this.ws.onclose = () => {
        this.isConnected = false;
        this._notify('connection', { connected: false });
        this._scheduleReconnect();
      };

      this.ws.onerror = (err) => {
        this.isConnected = false;
        this._notify('connection', { connected: false, error: err });
      };
    } catch (err) {
      this.isConnected = false;
      this._scheduleReconnect();
    }
  }

  _scheduleReconnect() {
    if (this.reconnectTimer) return;

    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.reconnectDelay = Math.min(this.reconnectDelay * 1.5, this.maxReconnectDelay);
      this.connect();
    }, this.reconnectDelay);
  }

  _handleIncomingMessage(payload) {
    const { type, data, level, message, timestamp } = payload;

    switch (type) {
      case 'state_changed':
        this._notify('state', {
          state: data?.state || 'IDLE',
          description: data?.description || '',
          timestamp,
        });
        break;

      case 'transcription':
        this._notify('transcription', {
          sender: data?.sender || 'User',
          text: data?.text || '',
          timestamp,
        });
        break;

      case 'tool_confirmation_request':
        this._notify('confirmation', data);
        break;

      case 'tool_executing':
        this._notify('executing', data);
        break;

      case 'telemetry':
        this._notify('telemetry', data);
        break;

      case 'log':
        this._notify('log', {
          level: level || 'INFO',
          message: message || '',
          timestamp: timestamp || new Date().toISOString(),
          data,
        });
        break;

      case 'system_response':
        this._notify('response', {
          message: message || data?.message || '',
          data,
          timestamp,
        });
        break;

      case 'error':
        this._notify('log', {
          level: 'ERROR',
          message: message || 'Erro no servidor',
          timestamp: new Date().toISOString(),
        });
        break;

      default:
        break;
    }
  }

  _notify(channel, data) {
    const callbacks = this.listeners[channel] || [];
    callbacks.forEach((cb) => {
      try {
        cb(data);
      } catch (err) {
        console.error(`[KON WebSocket] Error in listener for channel '${channel}':`, err);
      }
    });
  }

  subscribe(channel, callback) {
    if (!this.listeners[channel]) {
      this.listeners[channel] = [];
    }
    this.listeners[channel].push(callback);
    return () => {
      this.listeners[channel] = this.listeners[channel].filter((cb) => cb !== callback);
    };
  }

  sendCommand(commandText) {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      return false;
    }
    this.ws.send(JSON.stringify({
      type: 'command',
      command: commandText,
    }));
    return true;
  }

  confirmTool(id, confirmed) {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      return false;
    }
    this.ws.send(JSON.stringify({
      type: 'confirm_tool',
      id,
      confirmed,
    }));
    return true;
  }

  sendStateChange(stateName) {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      return false;
    }
    this.ws.send(JSON.stringify({
      type: 'set_state',
      state: stateName,
    }));
    return true;
  }
}

export const konWs = new KONWebSocketService();
