import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import React from 'react';
import { RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';

import { getDashboard } from '../api/endpoints';
import { Card, EmptyState, LoadingView, PrimaryButton, Screen, SecondaryButton, SectionTitle } from '../components/ui';
import { errorMessage, useApi } from '../hooks/useApi';
import { colors, spacing } from '../theme';
import { MainStackParamList } from '../navigation/MainNavigator';

type DashboardData = {
  patient: { full_name: string; patient_number: string } | null;
  latest_visit_summary: string;
  upcoming_appointments: Array<{
    id: number;
    doctor: { name: string } | null;
    department_name: string | null;
    appointment_date: string;
    consultation_type: string;
  }>;
  recent_lab_results: Array<{ id: number; test_name: string; result_value: string; result_date: string }>;
  active_prescription_items: Array<{
    id: number;
    drug_name: string;
    days_left: number | null;
    has_pending_refill: boolean;
  }>;
  total_paid: number;
  total_due: number;
  recent_notifications: Array<{ id: number; title: string; is_read: boolean }>;
  unread_notification_count: number;
  queue_snapshot: {
    queue_number: number;
    position: number;
    estimated_wait_minutes: number;
  } | null;
};

export default function DashboardScreen() {
  const navigation = useNavigation<NativeStackNavigationProp<MainStackParamList>>();
  const { data, loading, error, reload } = useApi<DashboardData>(() => getDashboard() as Promise<DashboardData>);

  if (loading && !data) return <LoadingView />;

  return (
    <Screen>
      <ScrollView
        contentContainerStyle={{ padding: spacing.md }}
        refreshControl={<RefreshControl refreshing={loading} onRefresh={reload} tintColor={colors.primary} />}
      >
        {error && <EmptyState message={errorMessage(error) ?? 'Could not load your dashboard.'} />}

        {data && !data.patient && (
          <EmptyState message="Your account isn't linked to a patient record yet. Contact reception for help." />
        )}

        {data?.patient && (
          <>
            <SectionTitle title={`Welcome, ${data.patient.full_name}`} />
            <Text style={styles.muted}>{data.patient.patient_number}</Text>

            {data.queue_snapshot && (
              <Card>
                <Text style={styles.cardTitle}>You're in the queue</Text>
                <Text style={styles.bigNumber}>#{data.queue_snapshot.queue_number}</Text>
                <Text style={styles.muted}>
                  Position {data.queue_snapshot.position} — about {data.queue_snapshot.estimated_wait_minutes} min wait
                </Text>
              </Card>
            )}

            <PrimaryButton title="Emergency Alert" onPress={() => navigation.navigate('EmergencyAlert')} />
            <View style={{ height: spacing.md }} />

            <SectionTitle title="Upcoming Appointments" />
            {data.upcoming_appointments.length === 0 ? (
              <EmptyState message="No upcoming appointments." />
            ) : (
              data.upcoming_appointments.map((appt) => (
                <Card key={appt.id}>
                  <Text style={styles.cardTitle}>
                    {appt.doctor ? appt.doctor.name : 'Doctor to be assigned'}
                  </Text>
                  <Text style={styles.muted}>{appt.department_name}</Text>
                  <Text style={styles.muted}>{new Date(appt.appointment_date).toLocaleString()}</Text>
                  {appt.consultation_type === 'TELEMEDICINE' && <Text style={styles.badge}>Telemedicine</Text>}
                </Card>
              ))
            )}

            <SectionTitle title="Active Prescriptions" />
            {data.active_prescription_items.length === 0 ? (
              <EmptyState message="No active prescriptions." />
            ) : (
              data.active_prescription_items.map((item) => (
                <Card key={item.id}>
                  <Text style={styles.cardTitle}>{item.drug_name}</Text>
                  <Text style={styles.muted}>
                    {item.days_left != null ? `${item.days_left} days left` : ''}
                    {item.has_pending_refill ? ' — refill requested' : ''}
                  </Text>
                </Card>
              ))
            )}

            <SectionTitle title="Recent Lab Results" />
            {data.recent_lab_results.length === 0 ? (
              <EmptyState message="No recent lab results." />
            ) : (
              data.recent_lab_results.map((result) => (
                <Card key={result.id}>
                  <Text style={styles.cardTitle}>{result.test_name}</Text>
                  <Text style={styles.muted}>{result.result_value}</Text>
                </Card>
              ))
            )}

            <SectionTitle title="Billing" />
            <Card>
              <Text style={styles.muted}>Paid: {data.total_paid}</Text>
              <Text style={styles.muted}>Outstanding: {data.total_due}</Text>
            </Card>

            <SectionTitle title={`Notifications${data.unread_notification_count ? ` (${data.unread_notification_count} new)` : ''}`} />
            {data.recent_notifications.length === 0 ? (
              <EmptyState message="No notifications." />
            ) : (
              data.recent_notifications.map((n) => (
                <Card key={n.id}>
                  <Text style={[styles.cardTitle, !n.is_read && { color: colors.primary }]}>{n.title}</Text>
                </Card>
              ))
            )}
            <SecondaryButton title="View all notifications" onPress={() => navigation.navigate('Notifications')} />
          </>
        )}
      </ScrollView>
    </Screen>
  );
}

const styles = StyleSheet.create({
  cardTitle: { color: colors.text, fontSize: 15, fontWeight: '600' },
  muted: { color: colors.textMuted, fontSize: 13, marginTop: 2 },
  bigNumber: { color: colors.primary, fontSize: 32, fontWeight: '800', marginVertical: 4 },
  badge: {
    color: colors.primary,
    fontSize: 12,
    marginTop: 4,
  },
});
