import client from "./client";

export interface TokenResponse {
  access_token: string;
  token_type: string;
}

export interface User {
  id: string;
  email: string;
  has_exchange_keys: boolean;
  created_at: string;
}

export async function register(email: string, password: string) {
  const { data } = await client.post<TokenResponse>("/auth/register", {
    email,
    password,
  });
  return data;
}

export async function login(email: string, password: string) {
  const { data } = await client.post<TokenResponse>("/auth/login", {
    email,
    password,
  });
  return data;
}

export async function getMe() {
  const { data } = await client.get<User>("/auth/me");
  return data;
}
