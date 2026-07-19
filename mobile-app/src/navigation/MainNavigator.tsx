import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import React from 'react';
import { Text } from 'react-native';

import { colors } from '../theme';
import AppointmentsScreen from '../screens/AppointmentsScreen';
import DashboardScreen from '../screens/DashboardScreen';
import EmergencyAlertScreen from '../screens/EmergencyAlertScreen';
import InvoicesScreen from '../screens/InvoicesScreen';
import LabResultsScreen from '../screens/LabResultsScreen';
import MessageThreadScreen from '../screens/MessageThreadScreen';
import MessagesScreen from '../screens/MessagesScreen';
import MoreScreen from '../screens/MoreScreen';
import NotificationsScreen from '../screens/NotificationsScreen';
import RecordsScreen from '../screens/RecordsScreen';
import RefillsScreen from '../screens/RefillsScreen';
import SettingsScreen from '../screens/SettingsScreen';
import TelemedicineHistoryScreen from '../screens/TelemedicineHistoryScreen';

export type TabParamList = {
  Dashboard: undefined;
  Appointments: undefined;
  Messages: undefined;
  More: undefined;
};

export type MainStackParamList = {
  Tabs: undefined;
  MessageThread: { doctorId: number; doctorName: string };
  Refills: undefined;
  Records: undefined;
  LabResults: undefined;
  Invoices: undefined;
  Notifications: undefined;
  EmergencyAlert: undefined;
  Settings: undefined;
  TelemedicineHistory: undefined;
};

const Tab = createBottomTabNavigator<TabParamList>();
const Stack = createNativeStackNavigator<MainStackParamList>();

// Plain-text/emoji glyphs rather than an icon font library (e.g.
// react-native-vector-icons) — a font-linking native module reintroduces
// the same class of Windows build pain (native codegen, MAX_PATH issues)
// that got react-native-gesture-handler removed from this project. No
// tabBarIcon was ever set here before, which is why the tab bar showed
// react-navigation's default fallback glyph instead of anything meaningful.
const TAB_ICONS: Record<keyof TabParamList, string> = {
  Dashboard: '\u{1F3E0}',
  Appointments: '\u{1F4C5}',
  Messages: '\u{1F4AC}',
  More: '\u{2630}',
};

function tabIcon(route: keyof TabParamList) {
  return ({ color }: { color: string }) => (
    <Text style={{ fontSize: 20, color }}>{TAB_ICONS[route]}</Text>
  );
}

const screenOptions = {
  headerStyle: { backgroundColor: colors.surface },
  headerTintColor: colors.text,
  headerShadowVisible: false,
};

function Tabs() {
  return (
    <Tab.Navigator
      screenOptions={{
        headerShown: false,
        tabBarStyle: { backgroundColor: colors.surface, borderTopColor: colors.border },
        tabBarActiveTintColor: colors.primary,
        tabBarInactiveTintColor: colors.textMuted,
      }}
    >
      <Tab.Screen
        name="Dashboard"
        component={DashboardScreen}
        options={{ tabBarIcon: tabIcon('Dashboard') }}
      />
      <Tab.Screen
        name="Appointments"
        component={AppointmentsScreen}
        options={{ tabBarIcon: tabIcon('Appointments') }}
      />
      <Tab.Screen
        name="Messages"
        component={MessagesScreen}
        options={{ tabBarIcon: tabIcon('Messages') }}
      />
      <Tab.Screen name="More" component={MoreScreen} options={{ tabBarIcon: tabIcon('More') }} />
    </Tab.Navigator>
  );
}

export default function MainNavigator() {
  return (
    <Stack.Navigator screenOptions={screenOptions}>
      <Stack.Screen name="Tabs" component={Tabs} options={{ headerShown: false }} />
      <Stack.Screen
        name="MessageThread"
        component={MessageThreadScreen}
        options={({ route }) => ({ title: route.params.doctorName })}
      />
      <Stack.Screen name="Refills" component={RefillsScreen} options={{ title: 'Prescription Refills' }} />
      <Stack.Screen name="Records" component={RecordsScreen} options={{ title: 'Medical Records' }} />
      <Stack.Screen name="LabResults" component={LabResultsScreen} options={{ title: 'Lab Results' }} />
      <Stack.Screen name="Invoices" component={InvoicesScreen} options={{ title: 'Billing' }} />
      <Stack.Screen name="Notifications" component={NotificationsScreen} options={{ title: 'Notifications' }} />
      <Stack.Screen
        name="EmergencyAlert"
        component={EmergencyAlertScreen}
        options={{ title: 'Emergency Alert', presentation: 'modal' }}
      />
      <Stack.Screen name="Settings" component={SettingsScreen} options={{ title: 'Settings' }} />
      <Stack.Screen
        name="TelemedicineHistory"
        component={TelemedicineHistoryScreen}
        options={{ title: 'Past Telemedicine Visits' }}
      />
    </Stack.Navigator>
  );
}
