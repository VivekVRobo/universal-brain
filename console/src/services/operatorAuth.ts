const STORAGE_KEY = "ub.operator-api-key";
const AUTH_CHANGED_EVENT = "ub-operator-auth-changed";

function notifyAuthChanged(): void {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event(AUTH_CHANGED_EVENT));
  }
}

export class OperatorAuth {
  static getToken(): string | null {
    if (typeof window === "undefined") return null;
    return window.sessionStorage.getItem(STORAGE_KEY);
  }

  static setToken(token: string): void {
    const normalized = token.trim();
    if (!normalized) throw new Error("Operator API key is required.");
    window.sessionStorage.setItem(STORAGE_KEY, normalized);
    notifyAuthChanged();
  }

  static clear(): void {
    if (typeof window !== "undefined") {
      window.sessionStorage.removeItem(STORAGE_KEY);
      notifyAuthChanged();
    }
  }

  static authorizationHeaders(): Record<string, string> {
    const token = this.getToken();
    return token ? { Authorization: `Bearer ${token}` } : {};
  }

  static websocketUrl(baseUrl: string): string {
    const token = this.getToken();
    if (!token) return baseUrl;
    const separator = baseUrl.includes("?") ? "&" : "?";
    return `${baseUrl}${separator}access_token=${encodeURIComponent(token)}`;
  }

  static subscribe(listener: () => void): () => void {
    window.addEventListener(AUTH_CHANGED_EVENT, listener);
    return () => window.removeEventListener(AUTH_CHANGED_EVENT, listener);
  }
}
