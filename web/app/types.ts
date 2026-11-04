// The API contract in TypeScript, mirroring docs/api-contract.md. Every field
// here is something the Python boundary actually returns; nothing is optional
// unless the boundary can omit it.

export type TaskStatus =
  | 'created'
  | 'discussing_request'
  | 'extracting'
  | 'generating_image'
  | 'prompt_ready'
  | 'outcome_unknown'
  | 'failed'

export interface ModelBinding {
  text: { model: string | null; reasoning_effort: string | null }
  image: { model: string | null; quality: string | null }
}

export interface Task {
  run_id: string
  case_id: string
  title: string
  status: TaskStatus
  created_at: string
  updated_at: string
  is_prompt_session: boolean
  prompt_ready: boolean
  error: string | null
  error_type: string | null
  running: boolean
  models: ModelBinding
}

export interface VisibleCopy {
  text: string
  language?: string | null
  uncertain?: boolean
}

export interface Revision {
  id: string
  parent_revision_id: string | null
  prompt_text: string
  origin: 'user_input' | 'vision_extraction' | 'assistant_revision' | 'manual_edit'
  digest: string
  created_at: string
  negative_prompt: string | null
  visible_copy: VisibleCopy[]
  uncertainties: string[]
  note: string | null
  restored_from: string | null
  source_image_id: string | null
}

export interface Message {
  id: string
  role: 'user' | 'assistant'
  text: string
  attachment_ids: string[]
  attachment_names: string[]
  created_at: string
  proposed_prompt: string | null
  proposed_revision_id: string | null
  edit_instruction: string | null
  conflict: boolean
  discrepancies: string[]
  in_reply_to: string | null
  turn_id: string | null
}

export interface Upload {
  id: string
  name: string
  role: 'reference' | 'mask' | 'discussion' | 'source_image'
  width: number | null
  height: number | null
  sha256: string
  created_at: string
  media_url: string
}

export interface AttemptSettings {
  model?: string | null
  quality?: string | null
  size?: string | null
  output_format?: string | null
}

export interface ReferenceRole {
  index: number
  image_id: string
  role: string
}

export interface Attempt {
  id: string
  action: 'generate' | 'edit'
  status: 'prepared' | 'submitting' | 'succeeded' | 'failed' | 'discarded' | 'outcome_unknown'
  request_text: string
  edit_instruction: string | null
  request_digest: string
  prompt_revision_id: string
  source_image_id: string | null
  reference_image_ids: string[]
  reference_roles: ReferenceRole[]
  mask_image_id: string | null
  settings: AttemptSettings
  reference_media_urls: string[]
  mask_media_url: string | null
  result_image_id: string | null
  created_at: string
  submitted_at: string | null
  error: { type?: string; message?: string } | null
  outcome_unknown: boolean
}

export interface ImageResult {
  id: string
  label: string
  action: 'generate' | 'edit'
  prompt_revision_id: string
  request_text: string
  parent_image_id: string | null
  attempt_id: string
  is_active: boolean
  created_at: string
  media_url: string
}

export interface Proposal {
  id: string
  kind: 'generate' | 'edit'
  base_revision_id: string
  prompt_text: string
  notes: string | null
  adopted_revision_id: string | null
  created_at: string
}

export interface PendingTurn {
  kind: 'chat' | 'extraction' | 'refine'
  turn_id: string
  created_at: string
}

export interface SessionSettings {
  image_quality?: string
  aspect_ratio?: [number, number] | number[]
  size?: string | null
  source_canvas?: { width: number; height: number } | null
  requested_canvas?: { width: number; height: number } | null
  canvas_origin?: 'default' | 'source' | 'user'
  canvas_note?: string | null
}

export interface Session {
  entry_mode: 'prompt' | 'image'
  settings: SessionSettings
  current_prompt_revision_id: string | null
  prompt_revisions: Revision[]
  messages: Message[]
  uploads: Upload[]
  image_attempts: Attempt[]
  image_results: ImageResult[]
  prompt_proposals: Proposal[]
  active_image_id: string | null
  pending_turn: PendingTurn | null
}

export interface TaskDetail {
  task: Task
  session: Session | null
}

export interface ErrorEnvelope {
  error: { code: string; message: string; details: unknown }
}

export interface CredentialView {
  configured: boolean
  masked: string | null
  source: string | null
}

export interface ModelProfile {
  model: string
  label: string
  description: string
}

export interface TextModelProfile extends ModelProfile {
  reasoning_efforts: string[]
  default_reasoning_effort: string
}

export interface ImageModelProfile extends ModelProfile {
  supports_max_quality: boolean
  supports_transparency: boolean
}

export interface SettingsPayload {
  language: string
  languages: { id: string; label: string }[]
  credential: CredentialView
  text_models: TextModelProfile[]
  image_models: ImageModelProfile[]
  qualities: string[]
  ratios: number[][]
}

export interface CorpusTag {
  id: string
  en: string
  zh: string
}

export interface CorpusFacet {
  id: string
  label: { en: string; zh: string }
  tags: CorpusTag[]
}

export interface CorpusRecord {
  id: string
  prompt: string
  negative_prompt: string | null
  tags: string[]
  source: { kind: string; run_id: string | null; url: string | null; note: string | null }
  image: { width: number | null; height: number | null; sha256: string; media_url: string } | null
  meta: Record<string, string | null>
  translations: Record<string, string | null>
  created_at: string
}

export interface CorpusSearch {
  total: number
  page: number
  limit: number
  records: CorpusRecord[]
}
