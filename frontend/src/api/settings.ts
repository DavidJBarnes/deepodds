import client from "./client";

export interface CoinbaseKeysStatus {
  has_keys: boolean;
  key_preview: string | null;
  valid: boolean;
}

export async function getCoinbaseKeysStatus() {
  const { data } = await client.get<CoinbaseKeysStatus>("/settings/coinbase-keys");
  return data;
}

export async function updateCoinbaseKeys(apiKey: string, privateKey: string) {
  const { data } = await client.put<CoinbaseKeysStatus>("/settings/coinbase-keys", {
    api_key: apiKey,
    private_key: privateKey,
  });
  return data;
}

export async function deleteCoinbaseKeys() {
  const { data } = await client.delete<CoinbaseKeysStatus>("/settings/coinbase-keys");
  return data;
}

export async function resetData() {
  const { data } = await client.post<{ status: string; cleared: string[] }>("/settings/reset-data");
  return data;
}
