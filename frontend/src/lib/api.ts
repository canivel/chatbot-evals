// ---- Type definitions ----

export interface EvalRun {
  id: string;
  name: string;
  status: "pending" | "running" | "completed" | "failed";
  conversations_count: number;
  overall_score: number;
  created_at: string;
  completed_at: string | null;
  config: {
    metrics: string[];
    judge_model: string;
  };
}

export interface MetricScore {
  metric: string;
  score: number;
  passed: number;
  failed: number;
  total: number;
}

export interface ConversationResult {
  id: string;
  conversation_id: string;
  overall_score: number;
  metric_scores: MetricScore[];
  flags: string[];
  created_at: string;
}

export interface EvalDetail extends EvalRun {
  metric_scores: MetricScore[];
  conversation_results: ConversationResult[];
}

export interface Connector {
  id: string;
  name: string;
  type: "mavenagi" | "intercom" | "zendesk" | "webhook" | "rest" | "file";
  status: "connected" | "disconnected" | "syncing" | "error";
  last_sync: string | null;
  conversations_synced: number;
  created_at: string;
}

export interface DashboardStats {
  total_evals: number;
  total_conversations: number;
  health_score: number;
  active_connectors: number;
}

export interface AlertRule {
  id: string;
  name: string;
  metric: string;
  threshold: number;
  operator: "lt" | "gt" | "lte" | "gte";
  enabled: boolean;
}

export interface OrgSettings {
  org_name: string;
  api_keys: { id: string; name: string; created_at: string; last_used: string | null }[];
  default_metrics: string[];
  default_judge_model: string;
  alert_rules: AlertRule[];
}

export interface TrendDataPoint {
  date: string;
  score: number;
  conversations: number;
}

// ---- API client ----

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function apiRequest<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const url = `${BASE_URL}${endpoint}`;

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...((options.headers as Record<string, string>) || {}),
  };

  // Add auth token if available (client-side only)
  if (typeof window !== "undefined") {
    const token = localStorage.getItem("auth_token");
    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
    }
  }

  const response = await fetch(url, {
    ...options,
    headers,
  });

  if (!response.ok) {
    const errorBody = await response.text().catch(() => "Unknown error");
    throw new ApiError(response.status, errorBody);
  }

  return response.json();
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public body: string
  ) {
    super(`API Error ${status}: ${body}`);
    this.name = "ApiError";
  }
}

// ---- API functions ----

export async function getDashboardStats(): Promise<DashboardStats> {
  return apiRequest<DashboardStats>("/api/v1/dashboard/stats");
}

export async function getEvalRuns(): Promise<EvalRun[]> {
  return apiRequest<EvalRun[]>("/api/v1/evals");
}

export async function getEvalDetail(id: string): Promise<EvalDetail> {
  return apiRequest<EvalDetail>(`/api/v1/evals/${id}`);
}

export async function createEvalRun(config: {
  name: string;
  connector_id: string;
  metrics: string[];
  judge_model: string;
}): Promise<EvalRun> {
  return apiRequest<EvalRun>("/api/v1/evals", {
    method: "POST",
    body: JSON.stringify(config),
  });
}

export async function getConnectors(): Promise<Connector[]> {
  return apiRequest<Connector[]>("/api/v1/connectors");
}

export async function createConnector(config: {
  name: string;
  type: Connector["type"];
  config: Record<string, string>;
}): Promise<Connector> {
  return apiRequest<Connector>("/api/v1/connectors", {
    method: "POST",
    body: JSON.stringify(config),
  });
}

export async function deleteConnector(id: string): Promise<void> {
  return apiRequest<void>(`/api/v1/connectors/${id}`, {
    method: "DELETE",
  });
}

export async function getSettings(): Promise<OrgSettings> {
  return apiRequest<OrgSettings>("/api/v1/settings");
}

export async function updateSettings(
  settings: Partial<OrgSettings>
): Promise<OrgSettings> {
  return apiRequest<OrgSettings>("/api/v1/settings", {
    method: "PATCH",
    body: JSON.stringify(settings),
  });
}

export async function getTrendData(
  days: number = 30
): Promise<TrendDataPoint[]> {
  return apiRequest<TrendDataPoint[]>(`/api/v1/reports/trends?days=${days}`);
}

export async function exportEval(
  id: string,
  format: "json" | "csv" | "html"
): Promise<Blob> {
  const url = `${BASE_URL}/api/v1/evals/${id}/export?format=${format}`;
  const headers: Record<string, string> = {};

  if (typeof window !== "undefined") {
    const token = localStorage.getItem("auth_token");
    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
    }
  }

  const response = await fetch(url, { headers });

  if (!response.ok) {
    throw new ApiError(response.status, await response.text());
  }

  return response.blob();
}
