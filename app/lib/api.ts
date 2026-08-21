const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/v1";

export type WorkflowStep = {
  step_key: string;
  label: string;
  position: number;
  status: "pending" | "running" | "succeeded" | "failed" | "skipped";
  progress: number;
  attempt: number;
  error_message: string | null;
};

export type Workflow = {
  id: string;
  task_type: string;
  status: "queued" | "running" | "waiting_provider" | "retry_wait" | "paused" | "canceling" | "canceled" | "succeeded" | "failed_retryable" | "failed_final" | "manual_intervention" | "cancelled";
  progress: number;
  input_payload: {
    script: string;
    title?: string | null;
    avatar_video_path: string;
    audio_path: string;
    aspect_ratio: string;
    quality: string;
    provider: "auto" | "duix" | "opentalking";
    execution_mode: "auto" | "local" | "self_hosted" | "cloud_api";
    selected_provider?: string;
    selected_execution?: string;
    route_policy_version?: string;
  };
  output_payload: Record<string, unknown> | null;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
  steps: WorkflowStep[];
  route_decisions: ProviderRouteDecision[];
};

export type ProviderRouteDecision = {
  capability: string;
  requested_provider: string;
  requested_execution: string;
  selected_provider: string;
  selected_execution: string;
  policy_version: string;
  reason: string;
  candidates: Array<Record<string, unknown>>;
  created_at: string;
};

export type AvatarProvider = {
  provider_id: string;
  label: string;
  category: string;
  capabilities: string[];
  execution_modes: string[];
  render_ready: boolean;
  integration_state: string;
  reason: string | null;
  status: "ready" | "setup_required" | "unavailable";
  probe: Record<string, unknown>;
};

export type ProviderCatalog = {
  capability: string;
  policy_version: string;
  priority: string[];
  default_route: ProviderRouteDecision | { error: string };
  providers: AvatarProvider[];
};

export type IPProfile = {
  id: string;
  name: string;
  promise: string;
  audience: string;
  offer: string;
  voice: string;
  evidence: string;
  boundary: string;
  version: number;
  is_primary: boolean;
  created_at: string;
  updated_at: string;
};

export type Campaign = {
  id: string;
  name: string;
  goal: string;
  channels: string[];
  status: "draft" | "active" | "paused" | "completed";
  target_content_count: number;
  metadata_payload: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type ContentProject = {
  id: string;
  campaign_id: string | null;
  ip_profile_id: string | null;
  title: string;
  source_type: "idea" | "benchmark" | "product" | "copy";
  platform: string;
  brief: string;
  angle: string;
  script: string;
  status: "draft" | "script_ready" | "in_production" | "approved" | "published";
  created_at: string;
  updated_at: string;
};

export type AgentProject = {
  id: string;
  tenant_id: string;
  name: string;
  goal: string;
  status: string;
  settings_payload: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type ProductionOrderStatus =
  | "draft" | "planning" | "awaiting_plan_approval" | "queued" | "running"
  | "awaiting_decision" | "evaluating" | "retry_wait" | "paused" | "canceling"
  | "canceled" | "succeeded" | "failed_retryable" | "failed_final" | "manual_intervention";

export type ProductionOrder = {
  id: string;
  tenant_id: string;
  project_id: string;
  content_item_id: string | null;
  title: string;
  intent_text: string;
  intent_spec: Record<string, unknown>;
  automation_mode: "many_confirmations" | "key_checkpoints" | "automatic";
  checkpoint_policy: Record<string, unknown>;
  external_side_effect_policy: Record<string, unknown>;
  status: ProductionOrderStatus;
  budget_limit: string | null;
  max_auto_rework: number;
  auto_rework_count: number;
  created_at: string;
  updated_at: string;
};

export type AgentPlan = {
  id: string;
  version: number;
  goal: string;
  success_criteria: string[];
  plan_payload: {
    steps: Array<{
      key: string;
      capability: string;
      depends_on: string[];
      expected_artifact: string;
      evaluator: string;
      checkpoint: string;
      blocked_by_missing_input?: boolean;
    }>;
    termination_policy: string;
  };
  budget_estimate: string | null;
  status: "draft" | "active" | "superseded" | "completed";
  created_at: string;
};

export type AgentDecision = {
  id: string;
  reason_code: string;
  title: string;
  summary: string;
  options: Array<{ key: string; label: string }>;
  recommended_option: string | null;
  blocking: boolean;
  status: "pending" | "resolved" | "canceled";
  resolved_option: string | null;
  resolution_payload: Record<string, unknown> | null;
  created_at: string;
  resolved_at: string | null;
};

export type AgentArtifactVersion = {
  id: string;
  artifact_id: string;
  artifact_key: string | null;
  artifact_type: string | null;
  version: number;
  status: "candidate" | "approved" | "returned" | "superseded";
  content_payload: Record<string, unknown>;
  checksum: string | null;
  created_at: string;
  approved_at: string | null;
};

export type ProductionOrderOverview = {
  order: ProductionOrder;
  agent_run: {
    id: string;
    run_number: number;
    status: "planning" | "running" | "awaiting_decision" | "evaluating" | "succeeded" | "failed" | "canceled";
    stop_reason: string | null;
    created_at: string;
    started_at: string | null;
    finished_at: string | null;
  };
  plan: AgentPlan | null;
  decisions: AgentDecision[];
  artifact_versions: AgentArtifactVersion[];
};

type UploadedAsset = {
  asset_id: string;
  file_name: string;
  provider_path: string;
  download_url: string;
  content_type: string | null;
};

async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      "X-Tenant-Id": "local-tenant",
      "X-User-Id": "local-user",
      "X-Owner-Id": "local-user",
      ...init?.headers,
    },
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new Error(payload?.detail ?? `请求失败（${response.status}）`);
  }
  return response.json() as Promise<T>;
}

export async function uploadAsset(file: File, projectId?: string): Promise<UploadedAsset> {
  const formData = new FormData();
  formData.append("file", file);
  const query = projectId ? `?project_id=${encodeURIComponent(projectId)}` : "";
  return apiRequest<UploadedAsset>(`/assets/upload${query}`, { method: "POST", body: formData });
}

export async function submitDigitalHumanWorkflow(input: {
  script: string;
  title?: string;
  avatar_video_path: string;
  audio_path: string;
  aspect_ratio: "9:16" | "16:9" | "1:1";
  quality: "720p" | "1080p";
  provider: "auto" | "duix" | "opentalking";
  execution_mode?: "auto" | "local" | "self_hosted" | "cloud_api";
}): Promise<Workflow> {
  return apiRequest<Workflow>("/workflows/digital-human", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Idempotency-Key": crypto.randomUUID(),
    },
    body: JSON.stringify(input),
  });
}

export async function listWorkflows(): Promise<Workflow[]> {
  return apiRequest<Workflow[]>("/workflows");
}

export async function retryWorkflow(workflowId: string): Promise<Workflow> {
  return apiRequest<Workflow>(`/workflows/${workflowId}/retry`, { method: "POST" });
}

export async function listAvatarProviders(probe = true): Promise<ProviderCatalog> {
  return apiRequest<ProviderCatalog>(`/providers?probe=${probe ? "true" : "false"}`);
}

export async function previewAvatarRoute(input: {
  provider: "auto" | "duix" | "opentalking";
  execution_mode?: "auto" | "local" | "self_hosted" | "cloud_api";
}): Promise<ProviderRouteDecision> {
  return apiRequest<ProviderRouteDecision>("/providers/route-preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      provider: input.provider,
      execution_mode: input.execution_mode ?? "auto",
    }),
  });
}

export function providerAssetUrl(assetPath: string): string {
  const encodedPath = assetPath.split("/").map(encodeURIComponent).join("/");
  return `${API_BASE_URL}/assets/provider-file/${encodedPath}`;
}

export async function listIPProfiles(): Promise<IPProfile[]> {
  return apiRequest<IPProfile[]>("/business/ip-profiles");
}

export async function saveIPProfile(input: Omit<IPProfile, "id" | "version" | "created_at" | "updated_at"> & { id?: string }): Promise<IPProfile> {
  const { id, ...payload } = input;
  return apiRequest<IPProfile>(id ? `/business/ip-profiles/${id}` : "/business/ip-profiles", {
    method: id ? "PATCH" : "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function listCampaigns(): Promise<Campaign[]> {
  return apiRequest<Campaign[]>("/business/campaigns");
}

export async function createCampaign(input: Pick<Campaign, "name" | "goal" | "channels" | "status" | "target_content_count">): Promise<Campaign> {
  return apiRequest<Campaign>("/business/campaigns", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...input, metadata_payload: {} }),
  });
}

export async function listContentProjects(): Promise<ContentProject[]> {
  return apiRequest<ContentProject[]>("/business/content-projects");
}

export async function createContentProject(input: Omit<ContentProject, "id" | "created_at" | "updated_at">): Promise<ContentProject> {
  return apiRequest<ContentProject>("/business/content-projects", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

export async function updateContentProject(projectId: string, input: Partial<Omit<ContentProject, "id" | "created_at" | "updated_at">>): Promise<ContentProject> {
  return apiRequest<ContentProject>(`/business/content-projects/${projectId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

export async function listAgentProjects(): Promise<AgentProject[]> {
  return apiRequest<AgentProject[]>("/projects");
}

export async function createAgentProject(input: { name: string; goal: string }): Promise<AgentProject> {
  return apiRequest<AgentProject>("/projects", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...input, settings_payload: {} }),
  });
}

export async function listProductionOrders(): Promise<ProductionOrder[]> {
  return apiRequest<ProductionOrder[]>("/production-orders");
}

export async function getProductionOrder(orderId: string): Promise<ProductionOrderOverview> {
  return apiRequest<ProductionOrderOverview>(`/production-orders/${orderId}`);
}

export async function createProductionOrder(input: {
  project_id: string;
  title?: string;
  intent_text: string;
  automation_mode: "many_confirmations" | "key_checkpoints" | "automatic";
  inputs?: Record<string, unknown>;
}, idempotencyKey: string): Promise<ProductionOrderOverview> {
  return apiRequest<ProductionOrderOverview>("/production-orders", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Idempotency-Key": idempotencyKey,
    },
    body: JSON.stringify(input),
  });
}

export async function resolveAgentDecision(
  decisionId: string,
  optionKey: string,
  payload: Record<string, unknown> = {},
): Promise<ProductionOrderOverview> {
  return apiRequest<ProductionOrderOverview>(`/decisions/${decisionId}/resolve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ option_key: optionKey, payload }),
  });
}

export async function updateProductionOrderInputs(orderId: string, input: {
  script: string;
  audio_asset_id: string;
  avatar_asset_id: string;
  aspect_ratio?: "9:16" | "16:9" | "1:1";
  quality?: "720p" | "1080p";
}): Promise<ProductionOrderOverview> {
  return apiRequest<ProductionOrderOverview>(`/production-orders/${orderId}/inputs`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

export async function reviewAgentArtifact(
  versionId: string,
  action: "approve" | "return",
  note = "",
): Promise<AgentArtifactVersion> {
  return apiRequest<AgentArtifactVersion>(`/artifact-versions/${versionId}/${action}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ note }),
  });
}
