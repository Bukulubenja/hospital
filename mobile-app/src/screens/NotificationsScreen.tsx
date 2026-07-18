import React from 'react';
import { ScrollView, Text } from 'react-native';

import { getNotifications, markAllNotificationsRead } from '../api/endpoints';
import { Card, EmptyState, LoadingView, Screen, SecondaryButton } from '../components/ui';
import { errorMessage, useApi } from '../hooks/useApi';
import { colors, spacing } from '../theme';

type Notification = {
  id: number;
  title: string;
  description: string;
  is_read: boolean;
  created_at: string;
};

export default function NotificationsScreen() {
  const { data, loading, error, reload } = useApi<Notification[]>(
    () => getNotifications() as Promise<Notification[]>,
  );

  const handleMarkAllRead = async () => {
    await markAllNotificationsRead();
    reload();
  };

  if (loading) return <LoadingView />;

  return (
    <Screen>
      <ScrollView contentContainerStyle={{ padding: spacing.md }}>
        {error && <EmptyState message={errorMessage(error) ?? 'Could not load notifications.'} />}
        <SecondaryButton title="Mark all as read" onPress={handleMarkAllRead} />
        {(data ?? []).length === 0 ? (
          <EmptyState message="No notifications." />
        ) : (
          data!.map((n) => (
            <Card key={n.id}>
              <Text
                style={{
                  color: n.is_read ? colors.text : colors.primary,
                  fontSize: 15,
                  fontWeight: '600',
                }}
              >
                {n.title}
              </Text>
              {n.description ? (
                <Text style={{ color: colors.textMuted, fontSize: 13 }}>{n.description}</Text>
              ) : null}
              <Text style={{ color: colors.textMuted, fontSize: 12, marginTop: 4 }}>
                {new Date(n.created_at).toLocaleString()}
              </Text>
            </Card>
          ))
        )}
      </ScrollView>
    </Screen>
  );
}
