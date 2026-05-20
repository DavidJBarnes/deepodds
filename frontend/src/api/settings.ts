import client from "./client";

export interface KalshiKeysStatus {
  has_keys: boolean;
  key_id_preview: string | null;
}

export async function getKalshiKeysStatus() {
  const { data } = await client.get<KalshiKeysStatus>("/settings/kalshi-keys");
  return data;
}

export async function updateKalshiKeys(apiKeyId: string, apiPrivateKey: string) {
  const { data } = await client.put<KalshiKeysStatus>("/settings/kalshi-keys", {
    api_key_id: apiKeyId,
    api_private_key: apiPrivateKey,
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
}

export async function getKalshiBalance() {
  const { data } = await client.get<KalshiBalance>("/settings/kalshi-balance");
  return data;
}

export interface CoinbaseKeysStatus {
  has_keys: boolean;
  key_preview: string | null;
}

export async function getCoinbaseKeysStatus() {
  const { data } = await client.get<CoinbaseKeysStatus>("/settings/coinbase-keys");
  return data;
}

export async function updateCoinbaseKeys(apiKey: string, apiSecret: string) {
  const { data } = await client.put<CoinbaseKeysStatus>("/settings/coinbase-keys", {
    api_key: apiKey,
    api_secret: apiSecret,
  });
  return data;
}

export async function deleteCoinbaseKeys() {
  const { data } = await client.delete<CoinbaseKeysStatus>("/settings/coinbase-keys");
  return data;
}
