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
  status: "queued" | "running" | "waiting_provider" | "succeeded" | "failed_retryable" | "failed_final" | "cancelled";
  progress: number;
  input_payload: {
    script: string;
    title?: string | null;
    avatar_video_path: string;
    audio_path: string;
    aspect_ratio: string;
    quality: string;
  };
  output_payload: Record<string, unknown> | null;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
  steps: WorkflowStep[];
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

export async function uploadAsset(file: File): Promise<UploadedAsset> {
  const formData = new FormData();
  formData.append("file", file);
  return apiRequest<UploadedAsset>("/assets/upload", { method: "POST", body: formData });
}

export async function submitDigitalHumanWorkflow(input: {
  script: string;
  title?: string;
  avatar_video_path: string;
  audio_path: string;
  aspect_ratio: "9:16" | "16:9" | "1:1";
  quality: "720p" | "1080p";
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

export function providerAssetUrl(assetPath: string): string {
  const encodedPath = assetPath.split("/").map(encodeURIComponent).join("/");
  return `${API_BASE_URL}/assets/provider-file/${encodedPath}`;
}
