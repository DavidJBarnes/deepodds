import client from "./client";

export interface KalshiKeysStatus {
  has_keys: boolean;
  key_preview: string | null;
  valid: boolean;
}

export async function getKalshiKeysStatus() {
  const { data } = await client.get<KalshiKeysStatus>("/settings/kalshi-keys");
  return data;
}

export async function updateKalshiKeys(apiKeyId: string, privateKeyPem: string) {
  const { data } = await client.put<KalshiKeysStatus>("/settings/kalshi-keys", {
    api_key_id: apiKeyId,
    private_key_pem: privateKeyPem,
  });
  return data;
}

export async function deleteKalshiKeys() {
  const { data } = await client.delete<KalshiKeysStatus>("/settings/kalshi-keys");
  return data;
}

export interface KalshiBalance {
  cash_cents: number;
  portfolio_cents: number;
  error: string | null;
}

export async function getKalshiBalance() {
  const { data } = await client.get<KalshiBalance>("/settings/kalshi-balance");
  return data;
}

export async function resetData() {
  const { data } = await client.post<{ status: string; cleared: string[] }>("/settings/reset-data");
  return data;
}
