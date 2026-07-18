import React from 'react';
import { ScrollView, Text } from 'react-native';

import { getInvoices } from '../api/endpoints';
import { Card, EmptyState, LoadingView, Screen } from '../components/ui';
import { errorMessage, useApi } from '../hooks/useApi';
import { colors, spacing } from '../theme';

type Invoice = {
  id: number;
  total_amount: number;
  status: string;
  created_at: string;
  amount_paid: number;
  balance_due: number;
  items: Array<{ id: number; service_name: string; quantity: number; subtotal: number }>;
};

export default function InvoicesScreen() {
  const { data, loading, error } = useApi<Invoice[]>(() => getInvoices() as Promise<Invoice[]>);

  if (loading) return <LoadingView />;

  return (
    <Screen>
      <ScrollView contentContainerStyle={{ padding: spacing.md }}>
        {error && <EmptyState message={errorMessage(error) ?? 'Could not load invoices.'} />}
        {(data ?? []).length === 0 ? (
          <EmptyState message="No invoices yet." />
        ) : (
          data!.map((invoice) => (
            <Card key={invoice.id}>
              <Text style={{ color: colors.text, fontSize: 15, fontWeight: '600' }}>
                Invoice #{invoice.id} — {invoice.status}
              </Text>
              <Text style={{ color: colors.textMuted, fontSize: 13 }}>
                {new Date(invoice.created_at).toLocaleDateString()}
              </Text>
              {invoice.items.map((item) => (
                <Text key={item.id} style={{ color: colors.textMuted, fontSize: 13 }}>
                  {item.service_name} x{item.quantity} — {item.subtotal}
                </Text>
              ))}
              <Text style={{ color: colors.text, fontSize: 13, marginTop: 4 }}>
                Total: {invoice.total_amount} · Paid: {invoice.amount_paid} · Due: {invoice.balance_due}
              </Text>
            </Card>
          ))
        )}
      </ScrollView>
    </Screen>
  );
}
