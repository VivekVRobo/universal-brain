const STORAGE_KEY = "ub.operator-api-key";

export class OperatorAuth {
  static getToken(): string | null {
    if (typeof window === "undefined") return null;
    return window.sessionStorage.getItem(STORAGE_KEY);
  }

  static setToken(token: string): void {
    const normalized = token.trim();
    if (!normalized) throw new Error("Operator API key is required.");
    window.sessionStorage.setItem(STORAGE_KEY, normalized);
  }

  static clear(): void {
    if (typeof window !== "undefined") {
      window.sessionStorage.removeItem(STORAGE_KEY);
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
}
