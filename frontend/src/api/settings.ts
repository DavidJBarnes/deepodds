import client from "./client";

export interface ExchangeKeysStatus {
  has_keys: boolean;
  key_preview: string | null;
  valid: boolean;
}

export async function getExchangeKeysStatus() {
  const { data } = await client.get<ExchangeKeysStatus>("/settings/exchange-keys");
  return data;
}

export async function updateExchangeKeys(apiKey: string, privateKey: string) {
  const { data } = await client.put<ExchangeKeysStatus>("/settings/exchange-keys", {
    api_key: apiKey,
    private_key: privateKey,
  });
  return data;
}

export async function deleteExchangeKeys() {
  const { data } = await client.delete<ExchangeKeysStatus>("/settings/exchange-keys");
  return data;
}

export async function resetData() {
  const { data } = await client.post<{ status: string; cleared: string[] }>("/settings/reset-data");
  return data;
}
