import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import React from 'react';
import { Pressable, ScrollView, Text } from 'react-native';

import { Card, Screen, SectionTitle } from '../components/ui';
import { MainStackParamList } from '../navigation/MainNavigator';
import { colors, spacing } from '../theme';

const ITEMS: Array<{ label: string; screen: keyof MainStackParamList }> = [
  { label: 'Prescription Refills', screen: 'Refills' },
  { label: 'Medical Records', screen: 'Records' },
  { label: 'Lab Results', screen: 'LabResults' },
  { label: 'Billing', screen: 'Invoices' },
  { label: 'Notifications', screen: 'Notifications' },
  { label: 'Settings', screen: 'Settings' },
];

export default function MoreScreen() {
  const navigation = useNavigation<NativeStackNavigationProp<MainStackParamList>>();

  return (
    <Screen>
      <ScrollView contentContainerStyle={{ padding: spacing.md }}>
        <SectionTitle title="More" />
        {ITEMS.map((item) => (
          <Pressable key={item.screen} onPress={() => navigation.navigate(item.screen as never)}>
            <Card>
              <Text style={{ color: colors.text, fontSize: 15, fontWeight: '600' }}>{item.label}</Text>
            </Card>
          </Pressable>
        ))}
      </ScrollView>
    </Screen>
  );
}
