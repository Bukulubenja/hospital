import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import React, { useState } from 'react';
import { ScrollView, StyleSheet, Text, View } from 'react-native';

import { cancelAppointment, getDepartments, getTelemedicine, requestTelemedicine } from '../api/endpoints';
import {
  Card,
  EmptyState,
  ErrorText,
  Input,
  LoadingView,
  PrimaryButton,
  Screen,
  SecondaryButton,
  SectionTitle,
} from '../components/ui';
import { ApiError } from '../context/AuthContext';
import { errorMessage, useApi } from '../hooks/useApi';
import { MainStackParamList } from '../navigation/MainNavigator';
import { colors, spacing } from '../theme';

type Appointment = {
  id: number;
  doctor: { name: string } | null;
  department: number | null;
  department_name: string | null;
  appointment_date: string;
  reason: string;
  status: string;
};

type Department = { id: number; name: string };

export default function AppointmentsScreen() {
  const navigation = useNavigation<NativeStackNavigationProp<MainStackParamList>>();
  const { data, loading, error, reload } = useApi<Appointment[]>(
    () => getTelemedicine() as Promise<Appointment[]>,
  );
  const { data: departments } = useApi<Department[]>(() => getDepartments() as Promise<Department[]>);

  const [showForm, setShowForm] = useState(false);
  const [departmentId, setDepartmentId] = useState<number | null>(null);
  const [dateInput, setDateInput] = useState(''); // YYYY-MM-DD HH:MM
  const [reason, setReason] = useState('');
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const handleRequest = async () => {
    if (!departmentId) {
      setFormError('Choose a department.');
      return;
    }
    const isoDate = parseLocalDateTime(dateInput);
    if (!isoDate) {
      setFormError('Enter the date/time as YYYY-MM-DD HH:MM.');
      return;
    }

    setSubmitting(true);
    setFormError(null);
    try {
      await requestTelemedicine({ department: departmentId, appointment_date: isoDate, reason });
      setShowForm(false);
      setDateInput('');
      setReason('');
      reload();
    } catch (e) {
      setFormError(e instanceof ApiError ? e.message : 'Could not request the appointment.');
    } finally {
      setSubmitting(false);
    }
  };

  const handleCancel = async (id: number) => {
    try {
      await cancelAppointment(id);
      reload();
    } catch {
      // Surfaced implicitly by the list not changing; keep it simple here.
    }
  };

  if (loading && !data) return <LoadingView />;

  return (
    <Screen>
      <ScrollView contentContainerStyle={{ padding: spacing.md }}>
        <SectionTitle title="Telemedicine Appointments" />
        {error && <EmptyState message={errorMessage(error) ?? 'Could not load appointments.'} />}

        {!showForm ? (
          <PrimaryButton title="Request a Telemedicine Visit" onPress={() => setShowForm(true)} />
        ) : (
          <Card>
            <Text style={styles.cardTitle}>New Request</Text>
            <View style={styles.deptRow}>
              {(departments ?? []).map((d) => (
                <SecondaryButton
                  key={d.id}
                  title={d.name + (departmentId === d.id ? ' ✓' : '')}
                  onPress={() => setDepartmentId(d.id)}
                />
              ))}
            </View>
            <Input
              placeholder="Date/time — YYYY-MM-DD HH:MM"
              value={dateInput}
              onChangeText={setDateInput}
            />
            <Input placeholder="Reason (optional)" value={reason} onChangeText={setReason} />
            <ErrorText message={formError} />
            <PrimaryButton title="Submit Request" onPress={handleRequest} loading={submitting} />
            <SecondaryButton title="Cancel" onPress={() => setShowForm(false)} />
          </Card>
        )}

        <View style={{ height: spacing.md }} />
        {(data ?? []).length === 0 ? (
          <EmptyState message="No upcoming telemedicine appointments." />
        ) : (
          data!.map((appt) => (
            <Card key={appt.id}>
              <Text style={styles.cardTitle}>{appt.doctor ? appt.doctor.name : 'Doctor to be assigned'}</Text>
              <Text style={styles.muted}>{appt.department_name}</Text>
              <Text style={styles.muted}>{new Date(appt.appointment_date).toLocaleString()}</Text>
              <Text style={styles.muted}>{appt.status}</Text>
              {appt.status === 'SCHEDULED' && (
                <SecondaryButton title="Cancel appointment" onPress={() => handleCancel(appt.id)} />
              )}
            </Card>
          ))
        )}

        <SecondaryButton
          title="View past telemedicine visits"
          onPress={() => navigation.navigate('TelemedicineHistory')}
        />
      </ScrollView>
    </Screen>
  );
}

function parseLocalDateTime(value: string): string | null {
  const match = value.trim().match(/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})$/);
  if (!match) return null;
  const [, y, mo, d, h, mi] = match;
  return `${y}-${mo}-${d}T${h}:${mi}:00`;
}

const styles = StyleSheet.create({
  cardTitle: { color: colors.text, fontSize: 15, fontWeight: '600', marginBottom: spacing.sm },
  muted: { color: colors.textMuted, fontSize: 13, marginTop: 2 },
  deptRow: { flexDirection: 'row', flexWrap: 'wrap', marginBottom: spacing.sm },
});
