export interface RunDetail { run_id: string; kind: string; status: string; submitted_at: string; links: { self: string; artifacts?: string | null; result?: string | null }; stage?: string | null; progress?: number; heartbeat_at?: string | null; }
export interface RunPage { items: RunDetail[]; next_cursor?: string | null; }
export interface paths { "/api/v1/runs": { get: { responses: { 200: { content: { "application/json": RunPage } } } } }; }
