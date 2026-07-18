import React, { useState } from 'react';
import { KeyboardAvoidingView, Platform, ScrollView, Text } from 'react-native';

import { Card, ErrorText, Input, PrimaryButton, Screen, SectionTitle } from '../components/ui';
import { useAuth } from '../context/AuthContext';
import { colors } from '../theme';

export default function HospitalPickerScreen() {
  const { chooseHospital } = useAuth();
  const [baseUrl, setBaseUrl] = useState('');
  const [subdomain, setSubdomain] = useState('');
  const [error, setError] = useState<string | null>(null);

  const handleContinue = () => {
    const trimmedUrl = baseUrl.trim().replace(/\/+$/, '');
    const trimmedSubdomain = subdomain.trim().toLowerCase();

    if (!/^https?:\/\/.+/.test(trimmedUrl)) {
      setError('Enter a full address starting with http:// or https://');
      return;
    }
    if (!trimmedSubdomain) {
      setError('Enter your hospital’s subdomain, e.g. "stjohns".');
      return;
    }

    setError(null);
    chooseHospital({ baseUrl: trimmedUrl, subdomain: trimmedSubdomain });
  };

  return (
    <Screen>
      <KeyboardAvoidingView
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
        style={{ flex: 1 }}
      >
        <ScrollView contentContainerStyle={{ padding: 24, flexGrow: 1, justifyContent: 'center' }}>
          <SectionTitle title="Connect to your hospital" />
          <Text style={{ color: colors.textMuted, fontSize: 13, marginBottom: 16 }}>
            Enter the address and subdomain your hospital gave you.
          </Text>
          <Card>
            <Input
              placeholder="https://yourhospital.example.com"
              autoCapitalize="none"
              autoCorrect={false}
              keyboardType="url"
              value={baseUrl}
              onChangeText={setBaseUrl}
            />
            <Input
              placeholder="Hospital subdomain, e.g. stjohns"
              autoCapitalize="none"
              autoCorrect={false}
              value={subdomain}
              onChangeText={setSubdomain}
            />
            <ErrorText message={error} />
            <PrimaryButton title="Continue" onPress={handleContinue} />
          </Card>
        </ScrollView>
      </KeyboardAvoidingView>
    </Screen>
  );
}
