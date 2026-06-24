export interface QualityOption {
  tier: number;
  label: string;
  lossless: boolean;
  fmt: string;
  bitrate_kbps?: number | null;
  note?: string | null;
}

export interface ProviderQualities {
  provider: string;
  label: string;
  qualities: QualityOption[];
}

export interface LibraryMatch {
  in_library: boolean;
  navidrome_id?: string | null;
  quality?: QualityOption | null;
  can_upgrade: boolean;
}

export interface TrackResult {
  title: string;
  artist: string;
  album?: string | null;
  source_url?: string | null;
  isrc?: string | null;
  duration_s?: number | null;
  cover_url?: string | null;
  ext_ids: Record<string, string>;
  providers: ProviderQualities[];
  library: LibraryMatch;
  best_tier?: number | null;
}

export interface AlbumResult {
  id: string;
  title: string;
  artist: string;
  provider: string;
  year?: number | null;
  cover_url?: string | null;
  total_tracks?: number | null;
}

export interface ArtistResult {
  id: string;
  name: string;
  provider: string;
  cover_url?: string | null;
}

export interface SearchResponse {
  kind: string;
  tracks: TrackResult[];
  albums: AlbumResult[];
  artists: ArtistResult[];
}

export interface AlbumDetail {
  album: AlbumResult;
  tracks: TrackResult[];
}

export interface Job {
  id: string;
  kind: string;
  status: string;
  provider?: string | null;
  requested_quality?: number | null;
  progress_pct: number;
  stage?: string | null;
  error?: string | null;
  result_path?: string | null;
  library_confirmed?: boolean | null;
  batch_id?: string | null;
  title?: string | null;
  origin?: string | null; // web | telegram | matrix
  created_at?: string | null;
  updated_at?: string | null;
  // Transient, from the live SSE event (not persisted on the backend DTO).
  speed?: string | null;
  eta_s?: number | null;
}

export interface BotStatus {
  name: string; // telegram | matrix
  enabled: boolean;
  configured: boolean;
  source?: string | null; // env | db | null
  running: boolean;
  connected: boolean;
  identity?: string | null;
  allowed_count: number;
  error?: string | null;
}

export interface Tool {
  name: string;
  installed_version?: string | null;
  latest_version?: string | null;
  update_available: boolean;
  repo?: string | null;
  latest_tag?: string | null;
  changelog?: string | null;
  last_checked_at?: string | null;
  managed: boolean;
}

export interface LibraryItem {
  id: number;
  title: string;
  artist: string;
  album?: string | null;
  fmt: string;
  bitrate_kbps?: number | null;
  quality_tier: number;
  source_provider: string;
  file_path: string;
  downloaded_at?: string | null;
}

export interface ProviderInfo {
  id: string;
  label: string;
  requires_credentials: boolean;
  enabled: boolean;
}

export interface Credential {
  provider: string;
  enabled: boolean;
  status?: string | null;
}

export interface SettingsData {
  metadata: string;
  providers: ProviderInfo[];
  credentials: Credential[];
  download_concurrency: number;
  download_layout: string;
  music_library_path: string;
}

export interface DownloadItemInput {
  provider: string;
  quality: number;
  track: {
    title: string;
    artist: string;
    album?: string | null;
    source_url?: string | null;
    isrc?: string | null;
    duration_s?: number | null;
    cover_url?: string | null;
    ext_ids?: Record<string, string>;
  };
}
