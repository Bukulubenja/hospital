import { useFocusEffect, useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import React, { useCallback } from 'react';
import { Pressable, ScrollView, Text } from 'react-native';

import { getMessages } from '../api/endpoints';
import { Card, EmptyState, LoadingView, Screen, SectionTitle } from '../components/ui';
import { errorMessage, useApi } from '../hooks/useApi';
import { MainStackParamList } from '../navigation/MainNavigator';
import { colors, spacing } from '../theme';

type Conversation = {
  doctor: { id: number; name: string };
  latest: { body: string; created_at: string; sender_is_me: boolean } | null;
  unread: number;
};

export default function MessagesScreen() {
  const navigation = useNavigation<NativeStackNavigationProp<MainStackParamList>>();
  const { data, loading, error, reload } = useApi<Conversation[]>(
    () => getMessages() as Promise<Conversation[]>,
  );

  useFocusEffect(
    useCallback(() => {
      reload();
    }, [reload]),
  );

  if (loading && !data) return <LoadingView />;

  return (
    <Screen>
      <ScrollView contentContainerStyle={{ padding: spacing.md }}>
        <SectionTitle title="Messages" />
        {error && <EmptyState message={errorMessage(error) ?? 'Could not load messages.'} />}
        {(data ?? []).length === 0 ? (
          <EmptyState message="You haven't messaged any doctors yet — you can message a doctor who has treated you." />
        ) : (
          data!.map((conv) => (
            <Pressable
              key={conv.doctor.id}
              onPress={() =>
                navigation.navigate('MessageThread', {
                  doctorId: conv.doctor.id,
                  doctorName: conv.doctor.name,
                })
              }
            >
              <Card>
                <Text style={{ color: colors.text, fontSize: 15, fontWeight: '600' }}>
                  {conv.doctor.name}
                  {conv.unread > 0 ? ` (${conv.unread})` : ''}
                </Text>
                {conv.latest && (
                  <Text style={{ color: colors.textMuted, fontSize: 13, marginTop: 2 }} numberOfLines={1}>
                    {conv.latest.sender_is_me ? 'You: ' : ''}
                    {conv.latest.body}
                  </Text>
                )}
              </Card>
            </Pressable>
          ))
        )}
      </ScrollView>
    </Screen>
  );
}
