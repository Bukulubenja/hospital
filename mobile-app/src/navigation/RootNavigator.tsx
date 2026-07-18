import { NavigationContainer, DarkTheme } from '@react-navigation/native';
import React from 'react';

import { LoadingView } from '../components/ui';
import { useAuth } from '../context/AuthContext';
import { colors } from '../theme';
import HospitalPickerScreen from '../screens/HospitalPickerScreen';
import LoginScreen from '../screens/LoginScreen';
import MainNavigator from './MainNavigator';

const navigationTheme = {
  ...DarkTheme,
  colors: {
    ...DarkTheme.colors,
    background: colors.background,
    card: colors.surface,
    border: colors.border,
    primary: colors.primary,
    text: colors.text,
  },
};

export default function RootNavigator() {
  const { hospital, isAuthenticated, isLoading } = useAuth();

  if (isLoading) {
    return <LoadingView />;
  }

  return (
    <NavigationContainer theme={navigationTheme}>
      {!hospital ? (
        <HospitalPickerScreen />
      ) : !isAuthenticated ? (
        <LoginScreen />
      ) : (
        <MainNavigator />
      )}
    </NavigationContainer>
  );
}
