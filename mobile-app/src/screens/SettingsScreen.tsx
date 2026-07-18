import React, { useState } from 'react';
import { ScrollView, Text } from 'react-native';

import { changePassword } from '../api/endpoints';
import { Card, ErrorText, Input, PrimaryButton, Screen, SecondaryButton, SectionTitle } from '../components/ui';
import { ApiError, useAuth } from '../context/AuthContext';
import { colors, spacing } from '../theme';

export default function SettingsScreen() {
  const { hospital, logout, changeHospital } = useAuth();
  const [oldPassword, setOldPassword] = useState('');
  const [newPassword1, setNewPassword1] = useState('');
  const [newPassword2, setNewPassword2] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [saving, setSaving] = useState(false);

  const handleChangePassword = async () => {
    setError(null);
    setSuccess(false);
    setSaving(true);
    try {
      await changePassword({
        old_password: oldPassword,
        new_password1: newPassword1,
        new_password2: newPassword2,
      });
      setSuccess(true);
      setOldPassword('');
      setNewPassword1('');
      setNewPassword2('');
    } catch (e) {
      if (e instanceof ApiError && e.body && typeof e.body === 'object' && 'errors' in e.body) {
        const errors = (e.body as { errors: Record<string, string[]> }).errors;
        setError(Object.values(errors).flat().join(' '));
      } else {
        setError(e instanceof ApiError ? e.message : 'Could not change password.');
      }
    } finally {
      setSaving(false);
    }
  };

  return (
    <Screen>
      <ScrollView contentContainerStyle={{ padding: spacing.md }}>
        <SectionTitle title="Account" />
        <Card>
          <Text style={{ color: colors.textMuted }}>Hospital: {hospital?.subdomain}</Text>
        </Card>

        <SectionTitle title="Change Password" />
        <Card>
          <Input
            placeholder="Current password"
            secureTextEntry
            value={oldPassword}
            onChangeText={setOldPassword}
          />
          <Input
            placeholder="New password"
            secureTextEntry
            value={newPassword1}
            onChangeText={setNewPassword1}
          />
          <Input
            placeholder="Confirm new password"
            secureTextEntry
            value={newPassword2}
            onChangeText={setNewPassword2}
          />
          <ErrorText message={error} />
          {success && <Text style={{ color: colors.success, marginBottom: spacing.sm }}>Password changed.</Text>}
          <PrimaryButton title="Change Password" onPress={handleChangePassword} loading={saving} />
        </Card>

        <SectionTitle title="Session" />
        <SecondaryButton title="Log Out" onPress={logout} />
        <SecondaryButton title="Change Hospital" onPress={changeHospital} />
      </ScrollView>
    </Screen>
  );
}
