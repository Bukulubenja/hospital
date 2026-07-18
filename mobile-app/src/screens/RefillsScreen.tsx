import React from 'react';
import { ScrollView, Text } from 'react-native';

import { getRefills, requestRefill } from '../api/endpoints';
import { Card, EmptyState, LoadingView, Screen, SecondaryButton, SectionTitle } from '../components/ui';
import { errorMessage, useApi } from '../hooks/useApi';
import { colors, spacing } from '../theme';

type EligibleItem = {
  id: number;
  drug_name: string;
  quantity: number;
  has_pending_refill: boolean;
};

type RefillRequest = {
  id: number;
  drug_name: string;
  status: string;
  requested_at: string;
  denial_reason: string;
};

type RefillsData = { eligible_items: EligibleItem[]; refill_requests: RefillRequest[] };

export default function RefillsScreen() {
  const { data, loading, error, reload } = useApi<RefillsData>(() => getRefills() as Promise<RefillsData>);

  const handleRequest = async (itemId: number) => {
    try {
      await requestRefill(itemId);
      reload();
    } catch {
      // Errors here are rare (duplicate request) — reload will show current state.
      reload();
    }
  };

  if (loading && !data) return <LoadingView />;

  return (
    <Screen>
      <ScrollView contentContainerStyle={{ padding: spacing.md }}>
        {error && <EmptyState message={errorMessage(error) ?? 'Could not load refills.'} />}

        <SectionTitle title="Eligible for Refill" />
        {(data?.eligible_items ?? []).length === 0 ? (
          <EmptyState message="No dispensed prescriptions eligible for refill." />
        ) : (
          data!.eligible_items.map((item) => (
            <Card key={item.id}>
              <Text style={{ color: colors.text, fontSize: 15, fontWeight: '600' }}>{item.drug_name}</Text>
              <Text style={{ color: colors.textMuted, fontSize: 13, marginBottom: spacing.sm }}>
                Quantity: {item.quantity}
              </Text>
              {item.has_pending_refill ? (
                <Text style={{ color: colors.textMuted, fontSize: 13 }}>Refill request pending</Text>
              ) : (
                <SecondaryButton title="Request Refill" onPress={() => handleRequest(item.id)} />
              )}
            </Card>
          ))
        )}

        <SectionTitle title="Refill Requests" />
        {(data?.refill_requests ?? []).length === 0 ? (
          <EmptyState message="No refill requests yet." />
        ) : (
          data!.refill_requests.map((req) => (
            <Card key={req.id}>
              <Text style={{ color: colors.text, fontSize: 15, fontWeight: '600' }}>{req.drug_name}</Text>
              <Text style={{ color: colors.textMuted, fontSize: 13 }}>{req.status}</Text>
              {req.denial_reason ? (
                <Text style={{ color: colors.danger, fontSize: 13 }}>{req.denial_reason}</Text>
              ) : null}
            </Card>
          ))
        )}
      </ScrollView>
    </Screen>
  );
}
