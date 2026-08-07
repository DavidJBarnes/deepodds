// Shared API + domain types for the Verbatim console.

export type ParseStatus = 'pending' | 'parsed' | 'needs_review' | 'raw_rules';
export type StreamStatus = 'idle' | 'armed' | 'live' | 'dead';
export type DetectionState = 'confirmed' | 'rejected';

export interface MarketOut {
  id: number;
  ticker: string;
  title: string;
  raw_rules: string;
  parse_status: ParseStatus;
  speaker: string | null;
  deadline_utc: string | null;
  armed: boolean;
}

export interface PatternOut {
  id: number;
  phrase: string;
  variant: string;
  variant_kind: string;
  version: number;
  active: boolean;
  manual: boolean;
}

export interface StreamOut {
  id: number;
  url: string;
  label: string | null;
  status: StreamStatus;
  expected_speaker: string | null;
  armed_until: string | null;
  restart_count: number;
}

export interface DetectionOut {
  id: number;
  market_id: number;
  state: DetectionState;
  utterance_ts: string;
  stage1_transcript: string;
  stage2_transcript: string | null;
  matched_span: string | null;
  stage1_score: number;
  stage2_score: number | null;
  speaker_label: string | null;
  speaker_is_expected: boolean | null;
  clip_path: string | null;
  chunk_capture_ts: string | null;
  stage1_done_ts: string | null;
  candidate_ts: string | null;
  stage2_done_ts: string | null;
  alert_sent_ts: string | null;
  market_reaction_ts: string | null;
  edge_seconds: number | null;
}

export interface HeartbeatOut {
  id: number;
  service: string;
  stream_id: number | null;
  ts: string;
  audio_level: number | null;
  chunk_rate: number | null;
  restart_count: number | null;
}

export interface HealthOut {
  status: string;
  degraded: string[];
}

// ---- WebSocket event payloads ----

export interface WordTiming {
  text: string;
  start: number;
  end: number;
}

export interface TranscriptEvent {
  stream_id: number;
  text: string;
  words?: WordTiming[];
  speaker?: string | null;
}

export interface NearMissEvent {
  market_id: number;
  pattern_id: number;
  score: number;
  variant: string;
}

export interface MarketQuoteEvent {
  ticker: string;
  yes_bid: number | null;
  yes_ask: number | null;
}

export type WsMessage =
  | { type: 'transcript'; data: TranscriptEvent }
  | { type: 'near_miss'; data: NearMissEvent }
  | { type: 'detection'; data: DetectionOut }
  | { type: 'heartbeat'; data: HeartbeatOut }
  | { type: 'market'; data: MarketQuoteEvent }
  | { type: string; data: unknown };

// ---- Request bodies ----

export interface ArmStreamRequest {
  url: string;
  market_ids?: number[];
  armed_until?: string | null;
  expected_speaker?: string | null;
  label?: string | null;
}
