import React, { createContext, useCallback, useContext, useEffect, useState } from 'react';

import {
  ApiError,
  login as apiLogin,
  logout as apiLogout,
  restoreActiveHospitalFromStorage,
  setActiveHospital,
} from '../api/client';
import {
  HospitalConfig,
  clearHospitalConfig,
  clearTokens,
  loadTokens,
  saveHospitalConfig,
} from '../api/storage';

type AuthContextValue = {
  hospital: HospitalConfig | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  patientId: number | null;
  chooseHospital: (config: HospitalConfig) => Promise<void>;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  /** Clears tokens *and* the saved hospital — back to the hospital picker. */
  changeHospital: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [hospital, setHospital] = useState<HospitalConfig | null>(null);
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [patientId, setPatientId] = useState<number | null>(null);

  useEffect(() => {
    (async () => {
      const config = await restoreActiveHospitalFromStorage();
      setHospital(config);
      if (config) {
        const tokens = await loadTokens();
        setIsAuthenticated(!!tokens);
      }
      setIsLoading(false);
    })();
  }, []);

  const chooseHospital = useCallback(async (config: HospitalConfig) => {
    await saveHospitalConfig(config);
    setActiveHospital(config);
    setHospital(config);
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    const data = await apiLogin(username, password);
    setPatientId(data.patient_id);
    setIsAuthenticated(true);
  }, []);

  const logout = useCallback(async () => {
    await apiLogout();
    setIsAuthenticated(false);
    setPatientId(null);
  }, []);

  const changeHospital = useCallback(async () => {
    await clearTokens();
    await clearHospitalConfig();
    setActiveHospital(null);
    setIsAuthenticated(false);
    setPatientId(null);
    setHospital(null);
  }, []);

  return (
    <AuthContext.Provider
      value={{
        hospital,
        isAuthenticated,
        isLoading,
        patientId,
        chooseHospital,
        login,
        logout,
        changeHospital,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}

export { ApiError };
