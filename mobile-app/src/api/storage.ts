import AsyncStorage from '@react-native-async-storage/async-storage';
import * as Keychain from 'react-native-keychain';

/**
 * Hospital address/subdomain isn't sensitive — plain AsyncStorage. JWTs are
 * credentials — react-native-keychain (OS-level secure storage), never
 * AsyncStorage.
 */

const HOSPITAL_KEY = 'hms:hospital';
const TOKEN_SERVICE = 'hms.tokens';

export type HospitalConfig = {
  /** Full server URL, e.g. "https://stjohns.hms.example.com" or
   * "http://192.168.1.5:8000" for local dev against a LAN IP. */
  baseUrl: string;
  /** Always sent as X-Hospital-Subdomain (see hospital/middleware.py) —
   * harmless in production (ignored outside DEBUG), required for local dev
   * where the device can't reach the dev machine via a real subdomain. */
  subdomain: string;
};

export type Tokens = { access: string; refresh: string };

export async function saveHospitalConfig(config: HospitalConfig): Promise<void> {
  await AsyncStorage.setItem(HOSPITAL_KEY, JSON.stringify(config));
}

export async function loadHospitalConfig(): Promise<HospitalConfig | null> {
  const raw = await AsyncStorage.getItem(HOSPITAL_KEY);
  return raw ? JSON.parse(raw) : null;
}

export async function clearHospitalConfig(): Promise<void> {
  await AsyncStorage.removeItem(HOSPITAL_KEY);
}

export async function saveTokens(tokens: Tokens): Promise<void> {
  await Keychain.setGenericPassword('tokens', JSON.stringify(tokens), {
    service: TOKEN_SERVICE,
  });
}

export async function loadTokens(): Promise<Tokens | null> {
  const result = await Keychain.getGenericPassword({ service: TOKEN_SERVICE });
  if (!result) return null;
  return JSON.parse(result.password);
}

export async function clearTokens(): Promise<void> {
  await Keychain.resetGenericPassword({ service: TOKEN_SERVICE });
}
