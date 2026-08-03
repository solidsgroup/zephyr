let csrfToken: string | null = null;

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  headers.set("Accept", "application/json");
  if (options.body) headers.set("Content-Type", "application/json");
  if (csrfToken && !["GET", "HEAD"].includes(options.method ?? "GET")) {
    headers.set("X-CSRF-Token", csrfToken);
  }
  const response = await fetch(`/api/v1${path}`, { ...options, headers, credentials: "same-origin" });
  if (!response.ok) {
    let message = response.statusText;
    try {
      const data = (await response.json()) as { detail?: string };
      message = data.detail ?? message;
    } catch {
      // Preserve the HTTP status text when the response is not JSON.
    }
    throw new ApiError(response.status, message);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export async function currentUser() {
  const data = await api<{ user: import("./types").User; csrf_token: string | null }>("/auth/me");
  csrfToken = data.csrf_token;
  return data.user;
}

export async function publicApi<T>(path: string): Promise<T> {
  const response = await fetch(`/api/v1/public${path}`);
  if (!response.ok) throw new ApiError(response.status, response.statusText);
  return response.json() as Promise<T>;
}
