import React from 'react';
import { ScrollView, Text } from 'react-native';

import { getRecords } from '../api/endpoints';
import { Card, EmptyState, LoadingView, Screen, SectionTitle } from '../components/ui';
import { errorMessage, useApi } from '../hooks/useApi';
import { colors, spacing } from '../theme';

type RecordsData = {
  visits: Array<{
    id: number;
    doctor: { name: string } | null;
    department_name: string | null;
    visit_date: string;
    diagnosis_summary: string;
    status: string;
  }>;
  medical_records: Array<{ id: number; doctor: { name: string } | null; diagnosis: string; created_at: string }>;
  prescriptions: Array<{
    id: number;
    doctor: { name: string } | null;
    created_at: string;
    items: Array<{ id: number; drug_name: string; dosage: string }>;
  }>;
  lab_orders: Array<{
    id: number;
    doctor: { name: string } | null;
    status: string;
    created_at: string;
    results: Array<{ id: number; test_name: string; result_value: string }>;
  }>;
};

export default function RecordsScreen() {
  const { data, loading, error } = useApi<RecordsData>(() => getRecords() as Promise<RecordsData>);

  if (loading) return <LoadingView />;

  return (
    <Screen>
      <ScrollView contentContainerStyle={{ padding: spacing.md }}>
        {error && <EmptyState message={errorMessage(error) ?? 'Could not load records.'} />}

        <SectionTitle title="Visits" />
        {(data?.visits ?? []).length === 0 ? (
          <EmptyState message="No visits on record." />
        ) : (
          data!.visits.map((v) => (
            <Card key={v.id}>
              <Text style={{ color: colors.text, fontSize: 15, fontWeight: '600' }}>
                {v.doctor ? v.doctor.name : 'Unassigned'}
              </Text>
              <Text style={{ color: colors.textMuted, fontSize: 13 }}>
                {v.department_name} · {new Date(v.visit_date).toLocaleDateString()} · {v.status}
              </Text>
              {v.diagnosis_summary ? (
                <Text style={{ color: colors.textMuted, fontSize: 13, marginTop: 4 }}>{v.diagnosis_summary}</Text>
              ) : null}
            </Card>
          ))
        )}

        <SectionTitle title="Diagnoses" />
        {(data?.medical_records ?? []).length === 0 ? (
          <EmptyState message="No diagnosis records." />
        ) : (
          data!.medical_records.map((r) => (
            <Card key={r.id}>
              <Text style={{ color: colors.text, fontSize: 15, fontWeight: '600' }}>{r.diagnosis}</Text>
              <Text style={{ color: colors.textMuted, fontSize: 13 }}>
                {r.doctor?.name} · {new Date(r.created_at).toLocaleDateString()}
              </Text>
            </Card>
          ))
        )}

        <SectionTitle title="Prescriptions" />
        {(data?.prescriptions ?? []).length === 0 ? (
          <EmptyState message="No prescriptions on record." />
        ) : (
          data!.prescriptions.map((p) => (
            <Card key={p.id}>
              <Text style={{ color: colors.text, fontSize: 15, fontWeight: '600' }}>
                {new Date(p.created_at).toLocaleDateString()} — {p.doctor?.name}
              </Text>
              {p.items.map((item) => (
                <Text key={item.id} style={{ color: colors.textMuted, fontSize: 13 }}>
                  {item.drug_name} ({item.dosage})
                </Text>
              ))}
            </Card>
          ))
        )}

        <SectionTitle title="Lab Orders" />
        {(data?.lab_orders ?? []).length === 0 ? (
          <EmptyState message="No lab orders on record." />
        ) : (
          data!.lab_orders.map((order) => (
            <Card key={order.id}>
              <Text style={{ color: colors.text, fontSize: 15, fontWeight: '600' }}>
                {new Date(order.created_at).toLocaleDateString()} — {order.status}
              </Text>
              {order.results.map((r) => (
                <Text key={r.id} style={{ color: colors.textMuted, fontSize: 13 }}>
                  {r.test_name}: {r.result_value}
                </Text>
              ))}
            </Card>
          ))
        )}
      </ScrollView>
    </Screen>
  );
}
