// Typed API client for Verbatim, ported from the standalone console.
//
// The `api.*` shape is kept identical to the original so the ported pages needed
// no rewrites — only the transport changed: bare `fetch` against `/api` becomes
// the shared axios client, which injects the DeepOdds bearer token and redirects
// to /login on 401. Verbatim's own API had no auth at all; this is where that gap
// closes on the client side.
import { AxiosError } from "axios";
import client from "./client";
import type {
  ArmStreamRequest,
  DetectionOut,
  DetectionState,
  HealthOut,
  HeartbeatOut,
  MarketOut,
  PatternOut,
} from "@/types/verbatim";
import type { StreamOut } from "@/types/verbatim";

/** The ported pages branch on `err instanceof ApiError` to show `status: detail`.
 * axios throws AxiosError instead, so requests are wrapped to preserve that
 * contract rather than rewriting every call site's error handling. */
export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

/** Normalise an axios failure into ApiError, preferring FastAPI's `detail`. */
async function wrap<T>(run: () => Promise<T>): Promise<T> {
  try {
    return await run();
  } catch (e) {
    if (e instanceof AxiosError) {
      const detail =
        (e.response?.data as { detail?: string } | undefined)?.detail ?? e.message;
      throw new ApiError(e.response?.status ?? 0, detail);
    }
    throw e;
  }
}

const P = "/verbatim";

/** Cache-buster on GETs — the convention used throughout bot.ts. */
const nocache = () => ({ params: { _t: Date.now() } });

export interface DetectionQuery {
  state?: DetectionState;
  market_id?: number;
  limit?: number;
}

export const api = {
  async health(): Promise<HealthOut> {
    const { data } = await wrap(() => client.get<HealthOut>(`${P}/health`, nocache()));
    return data;
  },

  async markets(): Promise<MarketOut[]> {
    const { data } = await wrap(() => client.get<MarketOut[]>(`${P}/markets`, nocache()));
    return data;
  },

  async patterns(marketId: number): Promise<PatternOut[]> {
    const { data } = await wrap(() => client.get<PatternOut[]>(
      `${P}/markets/${marketId}/patterns`,
      nocache(),
    ));
    return data;
  },

  async addPattern(marketId: number, phrase: string): Promise<PatternOut[]> {
    const { data } = await wrap(() => client.post<PatternOut[]>(
      `${P}/markets/${marketId}/patterns`,
      { phrase },
    ));
    return data;
  },

  async setPatternActive(patternId: number, active: boolean): Promise<PatternOut> {
    const { data } = await wrap(() => client.patch<PatternOut>(`${P}/patterns/${patternId}`, {
      active,
    }));
    return data;
  },

  async armMarket(marketId: number, armed: boolean): Promise<MarketOut> {
    const { data } = await wrap(() => client.post<MarketOut>(`${P}/markets/${marketId}/arm`, {
      armed,
    }));
    return data;
  },

  async detections(query: DetectionQuery = {}): Promise<DetectionOut[]> {
    const { data } = await wrap(() => client.get<DetectionOut[]>(`${P}/detections`, {
      params: { ...query, _t: Date.now() },
    }));
    return data;
  },

  async detection(id: number): Promise<DetectionOut> {
    const { data } = await wrap(() => client.get<DetectionOut>(`${P}/detections/${id}`, nocache()));
    return data;
  },

  /** Presigned S3 URL for a detection's evidence WAV.
   *
   * Clips live in a private bucket and are never public: the API signs a
   * short-lived GET per request. `clip_path` on the detection is an S3 object
   * key, not a playable path, so it must go through here. */
  async clipUrl(detectionId: number): Promise<string> {
    const { data } = await wrap(() => client.get<{ url: string }>(
      `${P}/detections/${detectionId}/clip`,
      nocache(),
    ));
    return data.url;
  },

  async streams(): Promise<StreamOut[]> {
    const { data } = await wrap(() => client.get<StreamOut[]>(`${P}/streams`, nocache()));
    return data;
  },

  async armStream(body: ArmStreamRequest): Promise<StreamOut> {
    const { data } = await wrap(() => client.post<StreamOut>(`${P}/streams/arm`, body));
    return data;
  },

  async disarmStream(id: number): Promise<StreamOut> {
    const { data } = await wrap(() => client.post<StreamOut>(`${P}/streams/${id}/disarm`));
    return data;
  },

  async heartbeats(limit?: number): Promise<HeartbeatOut[]> {
    const { data } = await wrap(() => client.get<HeartbeatOut[]>(`${P}/heartbeats`, {
      params: { limit, _t: Date.now() },
    }));
    return data;
  },
};
