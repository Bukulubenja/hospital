import { useNavigation } from '@react-navigation/native';
import Geolocation from '@react-native-community/geolocation';
import React, { useState } from 'react';
import { PermissionsAndroid, Platform, ScrollView, Text, View } from 'react-native';

import { sendEmergencyAlert } from '../api/endpoints';
import { Card, ErrorText, Input, PrimaryButton, Screen, SecondaryButton, SectionTitle } from '../components/ui';
import { ApiError } from '../context/AuthContext';
import { colors, spacing } from '../theme';

const SEVERITIES = [
  { value: 'CRITICAL', label: 'Critical' },
  { value: 'URGENT', label: 'Urgent' },
  { value: 'MODERATE', label: 'Moderate' },
];

export default function EmergencyAlertScreen() {
  const navigation = useNavigation();
  const [severity, setSeverity] = useState<string | null>(null);
  const [details, setDetails] = useState('');
  const [shareLocation, setShareLocation] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState(false);

  const getCoordinates = (): Promise<{ latitude: number; longitude: number } | null> =>
    new Promise((resolve) => {
      Geolocation.getCurrentPosition(
        (position) => resolve({ latitude: position.coords.latitude, longitude: position.coords.longitude }),
        () => resolve(null), // Denied/unavailable — never blocks sending the alert.
        { enableHighAccuracy: false, timeout: 8000 },
      );
    });

  const requestLocationPermission = async (): Promise<boolean> => {
    if (Platform.OS !== 'android') return true;
    try {
      const granted = await PermissionsAndroid.request(
        PermissionsAndroid.PERMISSIONS.ACCESS_FINE_LOCATION,
      );
      return granted === PermissionsAndroid.RESULTS.GRANTED;
    } catch {
      return false;
    }
  };

  const handleSend = async () => {
    if (!severity) {
      setError('Select a severity level.');
      return;
    }
    setError(null);
    setSending(true);

    let latitude: number | null = null;
    let longitude: number | null = null;
    if (shareLocation) {
      const hasPermission = await requestLocationPermission();
      if (hasPermission) {
        const coords = await getCoordinates();
        if (coords) {
          latitude = coords.latitude;
          longitude = coords.longitude;
        }
      }
    }

    try {
      await sendEmergencyAlert({
        severity,
        details,
        share_location: shareLocation,
        latitude,
        longitude,
      });
      setSent(true);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not send the alert. Try again.');
    } finally {
      setSending(false);
    }
  };

  if (sent) {
    return (
      <Screen>
        <ScrollView contentContainerStyle={{ padding: spacing.lg, flexGrow: 1, justifyContent: 'center' }}>
          <SectionTitle title="Alert Sent" />
          <Text style={{ color: colors.textMuted, marginBottom: spacing.md }}>
            Reception has been notified. For a life-threatening emergency, also call emergency services
            directly.
          </Text>
          <SecondaryButton title="Close" onPress={() => navigation.goBack()} />
        </ScrollView>
      </Screen>
    );
  }

  return (
    <Screen>
      <ScrollView contentContainerStyle={{ padding: spacing.md }}>
        <Text style={{ color: colors.textMuted, marginBottom: spacing.md }}>
          For a life-threatening emergency, call emergency services directly. This alert notifies
          reception at your hospital.
        </Text>
        <Card>
          <Text style={{ color: colors.text, fontWeight: '600', marginBottom: spacing.sm }}>Severity</Text>
          <View style={{ flexDirection: 'row', flexWrap: 'wrap', marginBottom: spacing.sm }}>
            {SEVERITIES.map((s) => (
              <SecondaryButton
                key={s.value}
                title={s.label + (severity === s.value ? ' ✓' : '')}
                onPress={() => setSeverity(s.value)}
              />
            ))}
          </View>
          <Input placeholder="Details (optional)" value={details} onChangeText={setDetails} multiline />
          <SecondaryButton
            title={shareLocation ? 'Sharing my location ✓' : 'Share my location'}
            onPress={() => setShareLocation((v) => !v)}
          />
          <ErrorText message={error} />
          <PrimaryButton title="Send Emergency Alert" onPress={handleSend} loading={sending} />
        </Card>
      </ScrollView>
    </Screen>
  );
}
