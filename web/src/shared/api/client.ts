import type { components } from "../../generated/schema";

export type RunDetail = components["schemas"]["RunDetail"];
export type RunPage = components["schemas"]["Page_RunDetail_"];

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number) {
    super(`request failed: ${status}`);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  if (!response.ok) {
    throw new ApiError(response.status);
  }
  return response.json() as Promise<T>;
}

export const apiClient = {
  get: <T>(path: string): Promise<T> => request<T>(path),
  post: <T, B>(path: string, body: B, headers?: HeadersInit): Promise<T> =>
    request<T>(path, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...headers },
      body: JSON.stringify(body),
    }),
  put: <T, B>(path: string, body: B): Promise<T> =>
    request<T>(path, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
};

export function listRuns(cursor?: string): Promise<RunPage> {
  const query = cursor ? `?cursor=${encodeURIComponent(cursor)}` : "";
  return apiClient.get<RunPage>(`/api/v1/runs${query}`);
}
