import React from 'react';
import { ScrollView, Text } from 'react-native';

import { getLabResults } from '../api/endpoints';
import { Card, EmptyState, LoadingView, Screen } from '../components/ui';
import { errorMessage, useApi } from '../hooks/useApi';
import { colors, spacing } from '../theme';

type LabResult = {
  id: number;
  test_name: string;
  result_value: string;
  normal_range: string;
  remarks: string;
  result_date: string;
};

export default function LabResultsScreen() {
  const { data, loading, error } = useApi<LabResult[]>(() => getLabResults() as Promise<LabResult[]>);

  if (loading) return <LoadingView />;

  return (
    <Screen>
      <ScrollView contentContainerStyle={{ padding: spacing.md }}>
        {error && <EmptyState message={errorMessage(error) ?? 'Could not load lab results.'} />}
        {(data ?? []).length === 0 ? (
          <EmptyState message="No lab results yet." />
        ) : (
          data!.map((result) => (
            <Card key={result.id}>
              <Text style={{ color: colors.text, fontSize: 15, fontWeight: '600' }}>{result.test_name}</Text>
              <Text style={{ color: colors.textMuted, fontSize: 13 }}>
                {result.result_value}
                {result.normal_range ? ` (normal: ${result.normal_range})` : ''}
              </Text>
              {result.remarks ? (
                <Text style={{ color: colors.textMuted, fontSize: 13 }}>{result.remarks}</Text>
              ) : null}
              <Text style={{ color: colors.textMuted, fontSize: 12, marginTop: 4 }}>
                {new Date(result.result_date).toLocaleString()}
              </Text>
            </Card>
          ))
        )}
      </ScrollView>
    </Screen>
  );
}
