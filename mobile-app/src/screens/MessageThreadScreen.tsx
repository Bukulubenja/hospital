import { RouteProp, useRoute } from '@react-navigation/native';
import React, { useState } from 'react';
import { KeyboardAvoidingView, Platform, ScrollView, StyleSheet, Text, View } from 'react-native';

import { getMessageThread, replyToThread } from '../api/endpoints';
import { EmptyState, ErrorText, Input, LoadingView, PrimaryButton, Screen } from '../components/ui';
import { ApiError } from '../context/AuthContext';
import { errorMessage, useApi } from '../hooks/useApi';
import { MainStackParamList } from '../navigation/MainNavigator';
import { colors, spacing } from '../theme';

type Message = { id: number; body: string; created_at: string; sender_is_me: boolean };

export default function MessageThreadScreen() {
  const route = useRoute<RouteProp<MainStackParamList, 'MessageThread'>>();
  const { doctorId } = route.params;
  const { data, loading, error, reload } = useApi<Message[]>(
    () => getMessageThread(doctorId) as Promise<Message[]>,
    [doctorId],
  );

  const [body, setBody] = useState('');
  const [sendError, setSendError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

  const handleSend = async () => {
    if (!body.trim()) return;
    setSending(true);
    setSendError(null);
    try {
      await replyToThread(doctorId, body.trim());
      setBody('');
      reload();
    } catch (e) {
      setSendError(e instanceof ApiError ? e.message : 'Could not send message.');
    } finally {
      setSending(false);
    }
  };

  if (loading && !data) return <LoadingView />;

  return (
    <Screen>
      <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : undefined} style={{ flex: 1 }}>
        <ScrollView contentContainerStyle={{ padding: spacing.md, flexGrow: 1 }}>
          {error && <EmptyState message={errorMessage(error) ?? 'Could not load this conversation.'} />}
          {(data ?? []).length === 0 ? (
            <EmptyState message="No messages yet — say hello." />
          ) : (
            data!.map((m) => (
              <View
                key={m.id}
                style={[styles.bubble, m.sender_is_me ? styles.bubbleMine : styles.bubbleTheirs]}
              >
                <Text style={styles.bubbleText}>{m.body}</Text>
                <Text style={styles.bubbleTime}>{new Date(m.created_at).toLocaleString()}</Text>
              </View>
            ))
          )}
        </ScrollView>
        <View style={styles.composer}>
          <ErrorText message={sendError} />
          <Input placeholder="Type a message…" value={body} onChangeText={setBody} multiline />
          <PrimaryButton title="Send" onPress={handleSend} loading={sending} />
        </View>
      </KeyboardAvoidingView>
    </Screen>
  );
}

const styles = StyleSheet.create({
  bubble: {
    maxWidth: '80%',
    borderRadius: 12,
    padding: spacing.sm,
    marginBottom: spacing.sm,
  },
  bubbleMine: {
    alignSelf: 'flex-end',
    backgroundColor: colors.primary,
  },
  bubbleTheirs: {
    alignSelf: 'flex-start',
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
  },
  bubbleText: { color: colors.text, fontSize: 14 },
  bubbleTime: { color: colors.textMuted, fontSize: 10, marginTop: 4 },
  composer: {
    padding: spacing.md,
    borderTopWidth: 1,
    borderTopColor: colors.border,
  },
});
