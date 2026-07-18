import {
  HospitalConfig,
  clearTokens,
  loadHospitalConfig,
  loadTokens,
  saveTokens,
} from './storage';

export class ApiError extends Error {
  status: number;
  body: unknown;

  constructor(status: number, body: unknown) {
    const detail =
      body && typeof body === 'object' && 'detail' in body
        ? String((body as { detail: unknown }).detail)
        : `Request failed (${status})`;
    super(detail);
    this.status = status;
    this.body = body;
  }
}

let activeHospital: HospitalConfig | null = null;

/** Set once after the hospital picker / on app start (loaded from storage). */
export function setActiveHospital(config: HospitalConfig | null): void {
  activeHospital = config;
}

export function getActiveHospital(): HospitalConfig | null {
  return activeHospital;
}

async function rawRequest(
  path: string,
  options: RequestInit,
  accessToken?: string,
): Promise<unknown> {
  if (!activeHospital) {
    throw new Error('No hospital selected — call setActiveHospital() first.');
  }

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    'X-Hospital-Subdomain': activeHospital.subdomain,
    ...((options.headers as Record<string, string>) ?? {}),
  };
  if (accessToken) {
    headers.Authorization = `Bearer ${accessToken}`;
  }

  const response = await fetch(`${activeHospital.baseUrl}${path}`, {
    ...options,
    headers,
  });

  const text = await response.text();
  const body = text ? JSON.parse(text) : null;

  if (!response.ok) {
    throw new ApiError(response.status, body);
  }
  return body;
}

async function refreshAccessToken(): Promise<string | null> {
  const tokens = await loadTokens();
  if (!tokens) return null;

  try {
    const data = (await rawRequest('/api/auth/refresh/', {
      method: 'POST',
      body: JSON.stringify({ refresh: tokens.refresh }),
    })) as { access: string; refresh?: string };

    const nextTokens = { access: data.access, refresh: data.refresh ?? tokens.refresh };
    await saveTokens(nextTokens);
    return nextTokens.access;
  } catch {
    // Refresh token expired/invalid — the user needs to log in again.
    await clearTokens();
    return null;
  }
}

/**
 * Authenticated request helper every screen uses. Transparently retries
 * once with a refreshed access token on a 401, mirroring how a browser
 * session just keeps working — the app never bothers the patient about
 * token expiry unless the refresh token itself has also expired.
 */
export async function apiRequest(path: string, options: RequestInit = {}): Promise<unknown> {
  const tokens = await loadTokens();
  if (!tokens) {
    throw new ApiError(401, { detail: 'Not authenticated' });
  }

  try {
    return await rawRequest(path, options, tokens.access);
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      const newAccess = await refreshAccessToken();
      if (newAccess) {
        return await rawRequest(path, options, newAccess);
      }
    }
    throw error;
  }
}

export async function login(
  username: string,
  password: string,
): Promise<{ role: string; patient_id: number | null }> {
  const data = (await rawRequest('/api/auth/login/', {
    method: 'POST',
    body: JSON.stringify({ username, password }),
  })) as { access: string; refresh: string; role: string; patient_id: number | null };

  await saveTokens({ access: data.access, refresh: data.refresh });
  return { role: data.role, patient_id: data.patient_id };
}

export async function logout(): Promise<void> {
  await clearTokens();
}

export async function restoreActiveHospitalFromStorage(): Promise<HospitalConfig | null> {
  const config = await loadHospitalConfig();
  setActiveHospital(config);
  return config;
}
