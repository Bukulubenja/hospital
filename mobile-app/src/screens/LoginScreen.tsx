import React, { useState } from 'react';
import { KeyboardAvoidingView, Platform, ScrollView, Text } from 'react-native';

import { Card, ErrorText, Input, PrimaryButton, Screen, SecondaryButton, SectionTitle } from '../components/ui';
import { ApiError, useAuth } from '../context/AuthContext';
import { colors } from '../theme';

export default function LoginScreen() {
  const { hospital, login, changeHospital } = useAuth();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const handleLogin = async () => {
    if (!username.trim() || !password) {
      setError('Enter your username and password.');
      return;
    }
    setError(null);
    setLoading(true);
    try {
      await login(username.trim(), password);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not log in. Check your connection.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Screen>
      <KeyboardAvoidingView
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
        style={{ flex: 1 }}
      >
        <ScrollView contentContainerStyle={{ padding: 24, flexGrow: 1, justifyContent: 'center' }}>
          <SectionTitle title="Patient Login" />
          <Text style={{ color: colors.textMuted, fontSize: 13, marginBottom: 16 }}>
            {hospital?.subdomain}
          </Text>
          <Card>
            <Input
              placeholder="Username"
              autoCapitalize="none"
              autoCorrect={false}
              value={username}
              onChangeText={setUsername}
            />
            <Input
              placeholder="Password"
              secureTextEntry
              value={password}
              onChangeText={setPassword}
            />
            <ErrorText message={error} />
            <PrimaryButton title="Log In" onPress={handleLogin} loading={loading} />
          </Card>
          <SecondaryButton title="Not your hospital? Change it" onPress={changeHospital} />
        </ScrollView>
      </KeyboardAvoidingView>
    </Screen>
  );
}
