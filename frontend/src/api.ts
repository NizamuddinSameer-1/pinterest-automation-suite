/**
 * Pinterest Realism Engine — Frontend API Client
 */



export interface Reference {
  id: string;
  campaign_id?: string;
  image_path: string;
  trend_label?: string;
  category?: string;
  status: string;
  created_at: string;
  // Set by GET /api/references. Nothing can be generated from a reference
  // without Visual DNA, and `status` does not track it (DNA seeded straight
  // into the table leaves status at "uploaded"), so the list reports it.
  has_visual_dna?: boolean;
  dna_version?: number | null;
  analysis?: any;
  visual_dna?: {
    id: string;
    version: number;
    is_manually_edited: boolean;
    data: any;
  };
}

export interface ReferenceAnalysisResult {
  reference_id: string;
  status: string;
  analysis: any;
  vault_synced?: boolean;
  vault_error?: string | null;
  visual_dna: { id: string; version: number; data: any };
}

export interface Product {
  id: string;
  campaign_id?: string;
  name: string;
  brand?: string;
  merchant?: string;
  product_url?: string;
  affiliate_url?: string;
  price?: number;
  currency: string;
  category?: string;
  seasons?: string[];
  colors?: string[];
  materials?: string[];
  key_attributes?: string[];
  product_image_path?: string;
  product_truth?: {
    asin?: string;
    title?: string;
    brand?: string;
    price_display?: string;
    price_amount?: number;
    currency?: string;
    star_rating?: number;
    review_count?: number;
    is_prime?: boolean;
    style_query?: string;
    smart_affiliate_url?: string;
    must_preserve?: string[];
    must_not_invent?: string[];
    allowed_scene_variations?: string[];
    [key: string]: any;
  };
  availability: string;
  created_at: string;
}

/**
 * Thrown by `api.generate` when the reference photograph and the selected product
 * are different kinds of object.
 *
 * A typed error rather than a string, because the panel has to offer the three ways
 * out (pick the right product, draft the product from the photo, or generate anyway)
 * and cannot do that from a message it has to parse.
 */
export class SubjectMismatchError extends Error {
  readonly productClass: string;
  readonly referenceClass: string;
  readonly referenceObjects: string[];
  readonly productName: string;
  readonly referenceId: string;

  constructor(detail: any) {
    super(String(detail?.message || 'The reference and the product are not the same kind of thing.'));
    this.name = 'SubjectMismatchError';
    this.productClass = String(detail?.product_class || 'unknown');
    this.referenceClass = String(detail?.reference_class || 'unknown');
    this.referenceObjects = Array.isArray(detail?.reference_objects) ? detail.reference_objects : [];
    this.productName = String(detail?.product_name || '');
    this.referenceId = String(detail?.reference_id || '');
  }
}

export interface Job {
  id: string;
  campaign_id?: string;
  reference_id: string;
  product_id: string;
  visual_dna_id?: string;
  scene?: any;
  current_state: string;
  provider: string;
  rework_count: number;
  failure_reason?: string;
  created_at: string;
  updated_at: string;
  prompt_versions?: Array<{
    id: string;
    version: number;
    prompt_text: string;
    is_rework: boolean;
    rework_instruction?: string;
    created_at: string;
  }>;
  outputs?: Array<{
    id: string;
    image_path: string;
    uploaded_at: string;
    critiques?: Array<{
      id: string;
      critique: {
        authenticity: string;
        product_fidelity: string;
        originality: string;
        defects: Array<{ severity: string; location: string; description: string }>;
        strengths: string[];
        decision: string;
        decision_reason: string;
      };
      decision: string;
      created_at: string;
    }>;
  }>;
}

export interface PinDraft {
  id: string;
  output_id: string;
  job_id: string;
  image_path?: string;
  title: string;
  description: string;
  keywords?: string[];
  destination_url?: string;
  board_name?: string;
  profile_id?: string;
  is_affiliate: boolean;
  is_ai_generated: boolean;
  disclosure: string;
  status: string;
  live_url?: string;
  scheduled_time?: string;
  human_decision?: string;
  rejection_reason?: string;
  exported_at?: string;
  created_at: string;
}

export interface PinterestProfile {
  id: string;
  name: string;
  folder: string;
  is_default: boolean;
  is_active: boolean;
  authenticated: boolean;
  profile_dir: string;
  cached_boards_count: number;
  created_at: string;
}

/**
 * How a bulk run should be spaced.
 *
 * Give `interval_minutes` **or** `daily_slots`. The backend planner refuses a
 * request with neither instead of inventing a spacing, so the UI must not send
 * an empty timing block and hope.
 */
export interface BulkScheduleOptions {
  pin_ids: string[];
  profile_id?: string;
  /** Local `YYYY-MM-DDTHH:MM` (what a datetime-local input gives) or a full ISO string. */
  start_time?: string;
  interval_minutes?: number;
  /** Fixed times of day, e.g. ['09:00', '13:30', '19:00']. */
  daily_slots?: string[];
  per_day_cap?: number;
  headless?: boolean;
}

export interface BulkPublishOptions {
  pin_ids: string[];
  profile_id?: string;
  allow_no_link?: boolean;
  force_board?: boolean;
  headless?: boolean;
}

/** One planned slot from the preview — no browser has run yet. */
export interface BulkPlannedTime {
  pin_id: string;
  title: string;
  board: string;
  /** Aware UTC ISO string. */
  scheduled_for: string;
  /** The same moment in the operator's local time, as Pinterest will show it. */
  local: string;
}

export interface BulkSchedulePreview {
  count: number;
  /** Pins that cannot be scheduled at all, each with the reason. */
  skipped: string[];
  /** Non-fatal warnings from the planner (slots overriding interval, heavy days…). */
  notes: string[];
  per_day: Record<string, number>;
  times: BulkPlannedTime[];
}

/** What the publisher observed for one pin. `status` is never optimistic. */
export interface BulkPinResult {
  pin_id: string;
  status: 'scheduled' | 'published' | 'failed' | string;
  /** What proved it: a captured pin id, on-screen text, or a navigation. */
  confirmed_by?: string | null;
  live_url?: string | null;
  board?: string | null;
  board_used?: string | null;
  scheduled_for?: string | null;
  scheduled_local?: string | null;
  error?: string | null;
  /**
   * login_required | builder_not_ready | field_not_accepted | board_not_found |
   * board_list_unreadable | schedule_not_accepted | not_confirmed | image_missing |
   * bad_request | unexpected
   *
   * board_not_found means the account has no such board (the error names the ones
   * it does have); board_list_unreadable means the picker never loaded, so the
   * board was never judged at all — that one is worth retrying, the other is not.
   */
  error_kind?: string | null;
  /** Path to the failure screenshot under data/debug/, when one was taken. */
  screenshot?: string | null;
  alerts?: string[];
}

export interface BulkScheduleResult {
  requested: number;
  attempted: number;
  scheduled: number;
  failed: number;
  skipped: string[];
  notes: string[];
  handled_by: string;
  results: BulkPinResult[];
  /** Present since publishing moved to a background run: poll it for progress. */
  run_id?: string;
  poll?: string;
  status?: string;
  times?: { pin_id: string; scheduled_for: string; local: string }[];
}

/**
 * A publish or bulk-schedule run, as `GET /pins/publish-runs/{run_id}` reports it.
 *
 * The browser runs in its own process, so this is the only progress source: the
 * child rewrites it after every pin. `results` therefore grows during a run —
 * `completed` of `total` — and is complete once `status` is done or error.
 *
 * `stalled` means the child stopped writing. It is reported, not repaired: the
 * browser may have got far enough to create a pin, so check Pinterest before
 * retrying rather than assuming nothing happened.
 */
export interface PublishRun {
  run_id: string;
  kind: 'publish' | 'bulk_schedule' | string;
  status: 'starting' | 'running' | 'done' | 'error' | string;
  started_at: string;
  finished_at?: string | null;
  total: number;
  completed: number;
  results: BulkPinResult[];
  /** Why the run itself died (not one pin) — includes the exception type. */
  error?: string | null;
  /** True once the API has written the outcome to the database. */
  applied?: boolean;
  /** Pin ids the API updated when it applied this run. */
  applied_pins?: string[];
  /** Pins never attempted, each with its reason. */
  skipped?: string[];
  notes?: string[];
  stalled?: boolean;
}

/** One image-generation backend, and whether it can run right now. */
export interface GenerationBackend {
  id: 'flow_api' | 'flow_ui' | 'pollinations' | string;
  label: string;
  primary: boolean;
  available: boolean;
  detail: string;
}

export interface GenerationBackendInfo {
  default: string;
  default_count: number;
  backends: GenerationBackend[];
}

/**
 * What `GET /jobs/{id}/generate/status` returns.
 *
 * `status` is written by the background runner. `produced_by` records which
 * backend actually made the images, and `attempts` lists every backend that was
 * tried and why it declined — so a failure explains itself instead of just
 * saying "no images".
 */
export interface GenerationStatus {
  status: 'not_started' | 'generating' | 'saving' | 'done' | 'error' | 'unknown' | string;
  job_id: string;
  backend?: string;
  produced_by?: string;
  message?: string;
  error?: string;
  attempts?: string[];
  image_count?: number;
  requested_count?: number;
  partial?: boolean;
  image_paths?: string[];
  retryable?: string;
  outputs?: Job['outputs'];
  [key: string]: any;
}

const API_BASE = '/api';

/**
 * `fetch`, with the two failures that used to be indistinguishable told apart.
 *
 * A `fetch` rejection is a *network* failure — nothing answered on port 8000, or
 * the Vite proxy could not reach it — and the browser only ever says "Failed to
 * fetch". Reported raw next to the word "publish", it read as "the publisher
 * broke" when the real answer was "run.py is not running". An HTTP error gets
 * FastAPI's `detail`, which is the actual reason.
 */
async function apiFetch(url: string, init?: RequestInit, fallback = 'Request failed'): Promise<Response> {
  let res: Response;
  try {
    res = await fetch(url, init);
  } catch (e) {
    throw new Error(
      `PRE's backend did not answer (${url}). Is run.py still running on port 8000? ` +
        `The browser reported: ${e instanceof Error ? e.message : String(e)}`
    );
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || fallback);
  }
  return res;
}

export const api = {
  // References
  getReferences: async (campaignId?: string): Promise<Reference[]> => {
    const url = campaignId ? `${API_BASE}/references?campaign_id=${campaignId}` : `${API_BASE}/references`;
    const res = await fetch(url);
    return res.json();
  },
  getReference: async (id: string): Promise<Reference> => {
    const res = await fetch(`${API_BASE}/references/${id}`);
    return res.json();
  },
  uploadReference: async (formData: FormData): Promise<{ id: string; status: string }> => {
    const res = await fetch(`${API_BASE}/references`, {
      method: 'POST',
      body: formData,
    });
    // A rejected upload (wrong type, over 10MB) returns 400 with a detail. Reading
    // the body regardless of status handed back `{detail: ...}` as if it were a
    // reference, and the panel then chained analysis onto `undefined`.
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      const detail = typeof err.detail === 'string' ? err.detail : JSON.stringify(err.detail);
      throw new Error(detail || 'The reference image could not be uploaded');
    }
    return res.json();
  },
  createReferenceFromProduct: async (productId: string, trendLabel?: string): Promise<any> => {
    const res = await fetch(`${API_BASE}/references/from-product`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ product_id: productId, trend_label: trendLabel }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      const detail = typeof err.detail === 'string' ? err.detail : JSON.stringify(err.detail);
      throw new Error(detail || 'Failed to create reference from product');
    }
    return res.json();
  },
  analyzeReference: async (id: string): Promise<ReferenceAnalysisResult> => {
    const res = await fetch(`${API_BASE}/references/${id}/analyze`, { method: 'POST' });
    // This is the only producer of Visual DNA, and it calls the vision model, so a
    // 502 is a real possibility. Returning res.json() regardless of status made a
    // failed analysis look like a finished one — the reference would still have no
    // DNA and the operator would only find out when /generate refused the job.
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      const detail = typeof err.detail === 'string' ? err.detail : JSON.stringify(err.detail);
      throw new Error(detail || 'Reference analysis failed');
    }
    return res.json();
  },
  updateVisualDNA: async (id: string, dna_json: any): Promise<any> => {
    const res = await fetch(`${API_BASE}/references/${id}/dna`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ dna_json }),
    });
    return res.json();
  },
  // Products
  getProducts: async (campaignId?: string): Promise<Product[]> => {
    const url = campaignId ? `${API_BASE}/products?campaign_id=${campaignId}` : `${API_BASE}/products`;
    const res = await fetch(url);
    return res.json();
  },
  getProduct: async (id: string): Promise<Product> => {
    const res = await fetch(`${API_BASE}/products/${id}`);
    return res.json();
  },
  createProduct: async (data: Partial<Product>): Promise<Product> => {
    const res = await fetch(`${API_BASE}/products`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    return res.json();
  },
  updateProductTruth: async (id: string, truth: any): Promise<any> => {
    const res = await fetch(`${API_BASE}/products/${id}/truth`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(truth),
    });
    return res.json();
  },
  deleteProduct: async (id: string): Promise<any> => {
    const res = await fetch(`${API_BASE}/products/${id}`, {
      method: 'DELETE',
    });
    return res.json();
  },

  // Jobs
  getJobs: async (state?: string): Promise<Job[]> => {
    const url = state ? `${API_BASE}/jobs?state=${state}` : `${API_BASE}/jobs`;
    const res = await fetch(url);
    return res.json();
  },
  getJob: async (id: string): Promise<Job> => {
    const res = await fetch(`${API_BASE}/jobs/${id}`);
    return res.json();
  },
  launchFlowCapture: async (): Promise<any> => {
    const res = await fetch(`${API_BASE}/jobs/flow/launch-capture`, { method: 'POST' });
    return res.json();
  },
  getFlowSessionStatus: async (): Promise<any> => {
    const res = await fetch(`${API_BASE}/jobs/flow/session-status`);
    return res.json();
  },
  getFlowProjects: async (): Promise<{ projects: string[]; total: number; strategy: string }> => {
    const res = await fetch(`${API_BASE}/jobs/flow/projects`);
    return res.json();
  },
  addFlowProject: async (url: string): Promise<any> => {
    const res = await fetch(`${API_BASE}/jobs/flow/projects`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || 'Failed to add Flow project');
    }
    return res.json();
  },
  removeFlowProject: async (uuid: string): Promise<any> => {
    const res = await fetch(`${API_BASE}/jobs/flow/projects/${uuid}`, {
      method: 'DELETE',
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || 'Failed to remove Flow project');
    }
    return res.json();
  },
  uploadBatch: async (jobId: string, files: File[]): Promise<any> => {
    const formData = new FormData();
    files.forEach((f) => formData.append('files', f));
    const res = await fetch(`${API_BASE}/jobs/${jobId}/upload-batch`, {
      method: 'POST',
      body: formData,
    });
    return res.json();
  },
  createJob: async (data: { reference_id: string; product_id?: string; campaign_id?: string; affiliate_url?: string }): Promise<Job> => {
    const res = await fetch(`${API_BASE}/jobs`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    return res.json();
  },
  generateLookbook: async (jobId: string, affiliate_url?: string): Promise<any> => {
    const res = await fetch(`${API_BASE}/jobs/${jobId}/lookbook`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ affiliate_url }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || 'Failed to generate lookbook');
    }
    return res.json();
  },
  generateScene: async (jobId: string): Promise<any> => {
    const res = await fetch(`${API_BASE}/jobs/${jobId}/scene`, { method: 'POST' });
    return res.json();
  },
  compilePrompt: async (jobId: string): Promise<any> => {
    const res = await fetch(`${API_BASE}/jobs/${jobId}/compile`, { method: 'POST' });
    return res.json();
  },
  // ── Generation (one endpoint) ──────────────────────────────────
  // `POST /jobs/{id}/generate` replaced /generate-auto and /generate-flow. It
  // runs the scene director and the 13-section compiler itself when they are
  // missing, so the Creative Lab no longer has to sequence those calls.
  getGenerationBackends: async (): Promise<GenerationBackendInfo> => {
    const res = await fetch(`${API_BASE}/jobs/generation/backends`);
    if (!res.ok) throw new Error('Could not read the generation backends');
    return res.json();
  },
  generate: async (
    jobId: string,
    options?: { backend?: string; count?: number; allowSubjectMismatch?: boolean }
  ): Promise<any> => {
    const params = new URLSearchParams();
    if (options?.backend) params.set('backend', options.backend);
    if (options?.count) params.set('count', String(options.count));
    // Only sent when the operator has said the photo is a style reference. Sending
    // it by default would put back the silence this whole guard removes.
    if (options?.allowSubjectMismatch) params.set('allow_subject_mismatch', 'true');
    const qs = params.toString();
    const res = await fetch(`${API_BASE}/jobs/${jobId}/generate${qs ? `?${qs}` : ''}`, {
      method: 'POST',
    });
    // A 409 here is real information — missing Visual DNA, empty must_preserve,
    // an illegal state hop, or a reference that shows something other than the
    // product. Returning res.json() regardless of status made those look like a
    // started run.
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      if (res.status === 409 && err?.detail?.error === 'subject_mismatch') {
        throw new SubjectMismatchError(err.detail);
      }
      const detail = typeof err.detail === 'string' ? err.detail : JSON.stringify(err.detail);
      throw new Error(detail || 'Generation could not be started');
    }
    return res.json();
  },
  previewPrompt: async (
    referenceId: string,
    productId?: string,
    allowSubjectMismatch: boolean = false
  ): Promise<{ prompt_text: string; is_valid: boolean; product_name: string; trend_label: string; scene: any }> => {
    const res = await fetch(`${API_BASE}/jobs/preview-prompt`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        reference_id: referenceId,
        product_id: productId || null,
        allow_subject_mismatch: allowSubjectMismatch,
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      if (res.status === 409 && err?.detail?.error === 'subject_mismatch') {
        throw new SubjectMismatchError(err.detail);
      }
      const detail = typeof err.detail === 'string' ? err.detail : JSON.stringify(err.detail);
      throw new Error(detail || 'Prompt preview failed');
    }
    return res.json();
  },
  getGenerationStatus: async (jobId: string): Promise<GenerationStatus> => {
    const res = await fetch(`${API_BASE}/jobs/${jobId}/generate/status`);
    if (!res.ok) throw new Error('Could not read generation status');
    return res.json();
  },
  uploadJobOutputs: async (jobId: string, formData: FormData): Promise<any> => {
    const res = await fetch(`${API_BASE}/jobs/${jobId}/outputs`, {
      method: 'POST',
      body: formData,
    });
    return res.json();
  },
  runCritique: async (jobId: string): Promise<any> => {
    const res = await fetch(`${API_BASE}/jobs/${jobId}/critique`, { method: 'POST' });
    return res.json();
  },
  reworkJob: async (jobId: string): Promise<any> => {
    const res = await fetch(`${API_BASE}/jobs/${jobId}/rework`, { method: 'POST' });
    return res.json();
  },

  // Pins
  getPins: async (status?: string): Promise<PinDraft[]> => {
    const url = status ? `${API_BASE}/pins?status=${status}` : `${API_BASE}/pins`;
    const res = await fetch(url);
    return res.json();
  },
  createPinDraft: async (data: { job_id: string; output_id: string }): Promise<PinDraft> => {
    const res = await fetch(`${API_BASE}/pins/draft`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    return res.json();
  },
  /**
   * Start a browser publish. Returns as soon as the run is running — poll
   * `getPublishRun(run_id)` for the outcome.
   *
   * It cannot resolve with the result: the browser takes minutes and lives in
   * another process, and holding the request open for it is how a pin that
   * Pinterest had already accepted came back as "Failed to fetch".
   */
  publishPin: async (pinId: string, profileId?: string): Promise<{ pin_id: string; profile_id?: string; run_id: string; status: string; poll: string; message: string }> => {
    const qs = profileId ? `?profile_id=${encodeURIComponent(profileId)}` : '';
    const res = await apiFetch(`${API_BASE}/pins/${pinId}/publish${qs}`, { method: 'POST' }, 'Publish failed');
    return res.json();
  },
  /** Progress for one publish or bulk-schedule run. Safe to call on a timer. */
  getPublishRun: async (runId: string): Promise<PublishRun> => {
    const res = await apiFetch(`${API_BASE}/pins/publish-runs/${runId}`, undefined, 'Could not read the publish run');
    return res.json();
  },
  schedulePin: async (pinId: string, scheduled_time: string): Promise<any> => {
    const res = await fetch(`${API_BASE}/pins/${pinId}/schedule`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ scheduled_time }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || 'Scheduling failed');
    }
    return res.json();
  },
  previewBulkSchedule: async (options: BulkScheduleOptions): Promise<BulkSchedulePreview> => {
    const res = await apiFetch(
      `${API_BASE}/pins/bulk-schedule/preview`,
      { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(options) },
      'Could not plan those times'
    );
    return res.json();
  },
  bulkSchedulePins: async (options: BulkScheduleOptions): Promise<BulkScheduleResult> => {
    const res = await apiFetch(
      `${API_BASE}/pins/bulk-schedule`,
      { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(options) },
      'Bulk scheduling failed'
    );
    return res.json();
  },
  bulkPublishPins: async (options: BulkPublishOptions): Promise<{
    run_id: string;
    poll: string;
    status: string;
    requested: number;
    attempted: number;
    skipped: string[];
    results: BulkPinResult[];
  }> => {
    const res = await apiFetch(
      `${API_BASE}/pins/bulk-publish`,
      { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(options) },
      'Bulk publishing failed'
    );
    return res.json();
  },
  getScheduledPins: async (): Promise<any[]> => {
    const res = await fetch(`${API_BASE}/pins/scheduled/list`);
    if (!res.ok) throw new Error('Could not load the schedule queue');
    return res.json();
  },
  cancelScheduledPin: async (entryId: string): Promise<any> => {
    const res = await fetch(`${API_BASE}/pins/scheduled/${entryId}`, { method: 'DELETE' });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || 'Could not cancel the scheduled pin');
    }
    return res.json();
  },
  getSchedulerStatus: async (): Promise<any> => {
    const res = await fetch(`${API_BASE}/pins/scheduler/status`);
    if (!res.ok) throw new Error('Could not read scheduler status');
    return res.json();
  },
  runSchedulerNow: async (): Promise<any> => {
    const res = await fetch(`${API_BASE}/pins/scheduler/run-now`, { method: 'POST' });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || 'Could not run the scheduler');
    }
    return res.json();
  },

  // ── Multiple Pinterest Profiles & Auth ─────────
  getPinterestProfiles: async (): Promise<PinterestProfile[]> => {
    const res = await fetch(`${API_BASE}/pins/auth/profiles`);
    if (!res.ok) throw new Error('Failed to load Pinterest profiles');
    return res.json();
  },
  createPinterestProfile: async (name: string, profileId?: string): Promise<PinterestProfile> => {
    const res = await fetch(`${API_BASE}/pins/auth/profiles`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, profile_id: profileId }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || 'Failed to create Pinterest profile');
    }
    return res.json();
  },
  deletePinterestProfile: async (profileId: string): Promise<any> => {
    const res = await fetch(`${API_BASE}/pins/auth/profiles/${profileId}`, { method: 'DELETE' });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || 'Failed to delete Pinterest profile');
    }
    return res.json();
  },
  setDefaultPinterestProfile: async (profileId: string): Promise<any> => {
    const res = await fetch(`${API_BASE}/pins/auth/profiles/${profileId}/default`, { method: 'POST' });
    if (!res.ok) throw new Error('Failed to set default profile');
    return res.json();
  },
  launchPinterestAuth: async (profileId?: string): Promise<{ status: string; message: string }> => {
    const qs = profileId ? `?profile_id=${encodeURIComponent(profileId)}` : '';
    const res = await fetch(`${API_BASE}/pins/auth/launch-login${qs}`, { method: 'POST' });
    return res.json();
  },
  getPinterestAuthStatus: async (profileId?: string): Promise<{ authenticated: boolean; profile_dir: string; message: string }> => {
    const qs = profileId ? `?profile_id=${encodeURIComponent(profileId)}` : '';
    const res = await fetch(`${API_BASE}/pins/auth/status${qs}`);
    return res.json();
  },
  getAccountBoards: async (profileId?: string): Promise<{
    boards: string[];
    count: number;
    default_board?: string;
    refresh: any;
    message: string;
    stale: boolean;
  }> => {
    const qs = profileId ? `?profile_id=${encodeURIComponent(profileId)}` : '';
    const res = await fetch(`${API_BASE}/pins/boards${qs}`);
    return res.json();
  },
  refreshAccountBoards: async (profileId?: string, visible: boolean = false): Promise<any> => {
    const params = new URLSearchParams();
    if (profileId) params.set('profile_id', profileId);
    if (visible) params.set('visible', 'true');
    const qs = params.toString();
    const res = await fetch(`${API_BASE}/pins/boards/refresh${qs ? `?${qs}` : ''}`, { method: 'POST' });
    return res.json();
  },
  approvePin: async (pinId: string): Promise<any> => {
    const res = await fetch(`${API_BASE}/pins/${pinId}/approve`, { method: 'POST' });
    return res.json();
  },
  rejectPin: async (pinId: string, reason: string, notes?: string): Promise<any> => {
    const res = await fetch(`${API_BASE}/pins/${pinId}/reject`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason, notes }),
    });
    return res.json();
  },

  // ── Diagnostics & Debugging ───────────────────
  getSystemStatus: async (): Promise<any> => {
    const res = await fetch(`${API_BASE}/debug/system-status`);
    if (!res.ok) throw new Error('Failed to fetch system diagnostics');
    return res.json();
  },
  getRecentErrors: async (limit: number = 20): Promise<any> => {
    const res = await fetch(`${API_BASE}/debug/recent-errors?limit=${limit}`);
    if (!res.ok) throw new Error('Failed to fetch recent errors');
    return res.json();
  },
  testLLM: async (): Promise<any> => {
    const res = await fetch(`${API_BASE}/debug/test-llm`, { method: 'POST' });
    return res.json();
  },
  testFlowSession: async (): Promise<any> => {
    const res = await fetch(`${API_BASE}/debug/test-flow-session`, { method: 'POST' });
    return res.json();
  },
  testPinterestSession: async (): Promise<any> => {
    const res = await fetch(`${API_BASE}/debug/test-pinterest-session`, { method: 'POST' });
    return res.json();
  },

  // ── Amazon Product Discovery & Ingestion ──────
  searchAmazon: async (keywords: string, category: string = 'All', itemCount: number = 8): Promise<{ success: boolean; count: number; items: AmazonItem[] }> => {
    const res = await fetch(`${API_BASE}/amazon/search`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ keywords, category, item_count: itemCount }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || 'Amazon search failed');
    }
    return res.json();
  },
  lookupAmazon: async (asinOrUrl: string): Promise<{ success: boolean; item: AmazonItem }> => {
    const res = await fetch(`${API_BASE}/amazon/lookup`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ asin_or_url: asinOrUrl }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || 'Amazon product lookup failed');
    }
    return res.json();
  },
  ingestAmazon: async (asinOrUrl: string, campaignId?: string, customKeywords?: string): Promise<{ success: boolean; product_id: string; asin: string; name: string; price: string; smart_affiliate_url: string; style_query: string }> => {
    const res = await fetch(`${API_BASE}/amazon/ingest`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ asin_or_url: asinOrUrl, campaign_id: campaignId, custom_keywords: customKeywords }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || 'Amazon product ingestion failed');
    }
    return res.json();
  },
};

export interface AmazonItem {
  asin: string;
  title: string;
  brand?: string;
  price?: string;
  price_amount?: number;
  currency?: string;
  star_rating?: number;
  review_count?: number;
  is_prime?: boolean;
  primary_image_url?: string;
  images?: string[];
  features?: string[];
  smart_url?: string;
  style_query?: string;
  verified_date?: string;
}


