import React from 'react';
import { ScrollView, Text } from 'react-native';

import { getTelemedicineHistory } from '../api/endpoints';
import { Card, EmptyState, LoadingView, Screen } from '../components/ui';
import { errorMessage, useApi } from '../hooks/useApi';
import { colors, spacing } from '../theme';

type PastAppointment = {
  id: number;
  doctor: { name: string } | null;
  department_name: string | null;
  appointment_date: string;
  status: string;
};

export default function TelemedicineHistoryScreen() {
  const { data, loading, error } = useApi<PastAppointment[]>(
    () => getTelemedicineHistory() as Promise<PastAppointment[]>,
  );

  if (loading) return <LoadingView />;

  return (
    <Screen>
      <ScrollView contentContainerStyle={{ padding: spacing.md }}>
        {error && <EmptyState message={errorMessage(error) ?? 'Could not load history.'} />}
        {(data ?? []).length === 0 ? (
          <EmptyState message="No past telemedicine visits." />
        ) : (
          data!.map((appt) => (
            <Card key={appt.id}>
              <Text style={{ color: colors.text, fontSize: 15, fontWeight: '600' }}>
                {appt.doctor ? appt.doctor.name : 'Unassigned'}
              </Text>
              <Text style={{ color: colors.textMuted, fontSize: 13, marginTop: 2 }}>
                {appt.department_name} · {new Date(appt.appointment_date).toLocaleString()}
              </Text>
              <Text style={{ color: colors.textMuted, fontSize: 13 }}>{appt.status}</Text>
            </Card>
          ))
        )}
      </ScrollView>
    </Screen>
  );
}
