// FrameWeave 新工作台的数据契约，字段与本地 Python API 一致。
export type Language = 'zh-CN' | 'en';
export type Scene = {
  id: string;
  title: string;
  narration: string;
  prompt: string;
  duration: number;
  media_asset_id?: string | null;
  audio_asset_id?: string | null;
  presenter_asset_id?: string | null;
  layout: 'full' | 'pip';
};
export type Project = {
  id: string;
  title: string;
  width: number;
  height: number;
  fps: number;
  language: Language;
  created_at: string;
  updated_at: string;
  revision: number;
  scenes: Scene[];
  final_asset_id?: string | null;
  rendered_revision?: number | null;
};
export type Asset = {
  id: string;
  project_id: string;
  kind: 'image' | 'video' | 'audio';
  filename: string;
  url: string;
  source: 'upload' | 'demo' | 'generated' | 'render';
};
export type Job = {
  id: string;
  project_id: string;
  scene_id?: string;
  operation: 'render' | 'generate_media' | 'generate_audio';
  params: Record<string, unknown>;
  status: 'queued' | 'running' | 'succeeded' | 'failed' | 'interrupted' | 'cancelled';
  progress: number;
  stage: string;
  result_asset_id?: string;
  error?: string;
  created_at: string;
  updated_at: string;
  result_applied?: boolean;
};
export type Recipe = { id: string; name: string; description: string };
export type Model = { id: string; label: string; kind: string };
export type Version = { revision: number; created_at: string; title: string };
export type Health = {
  status: string;
  product: string;
  version: string;
  ffmpeg_available: boolean;
};
