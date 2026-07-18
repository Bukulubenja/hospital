import { apiRequest } from './client';

// One function per hospital/api/urls.py route — keep this file a 1:1 mirror
// of that file rather than adding client-side business logic.

export const getDashboard = () => apiRequest('/api/patient/dashboard/');

export const cancelAppointment = (id: number) =>
  apiRequest(`/api/patient/appointments/${id}/cancel/`, { method: 'POST' });

export const getNotifications = () => apiRequest('/api/patient/notifications/');

export const markAllNotificationsRead = () =>
  apiRequest('/api/patient/notifications/mark-all-read/', { method: 'POST' });

export const sendEmergencyAlert = (payload: {
  severity: string;
  details?: string;
  share_location: boolean;
  latitude?: number | null;
  longitude?: number | null;
}) =>
  apiRequest('/api/patient/emergency-alert/', {
    method: 'POST',
    body: JSON.stringify(payload),
  });

export const changePassword = (payload: {
  old_password: string;
  new_password1: string;
  new_password2: string;
}) =>
  apiRequest('/api/patient/change-password/', {
    method: 'POST',
    body: JSON.stringify(payload),
  });

export const getMessages = () => apiRequest('/api/patient/messages/');

export const sendNewMessage = (payload: { doctor: number; body: string }) =>
  apiRequest('/api/patient/messages/', { method: 'POST', body: JSON.stringify(payload) });

export const getMessageThread = (doctorId: number) =>
  apiRequest(`/api/patient/messages/${doctorId}/`);

export const replyToThread = (doctorId: number, body: string) =>
  apiRequest(`/api/patient/messages/${doctorId}/`, {
    method: 'POST',
    body: JSON.stringify({ body }),
  });

export const getRefills = () => apiRequest('/api/patient/refills/');

export const requestRefill = (itemId: number) =>
  apiRequest(`/api/patient/refills/${itemId}/request/`, { method: 'POST' });

export const getTelemedicine = () => apiRequest('/api/patient/telemedicine/');

export const requestTelemedicine = (payload: {
  doctor?: number | null;
  department: number;
  appointment_date: string;
  reason?: string;
}) =>
  apiRequest('/api/patient/telemedicine/', { method: 'POST', body: JSON.stringify(payload) });

export const getTelemedicineHistory = () => apiRequest('/api/patient/telemedicine/history/');

export const getRecords = () => apiRequest('/api/patient/records/');

export const getLabResults = () => apiRequest('/api/patient/lab-results/');

export const getInvoices = () => apiRequest('/api/patient/invoices/');

export const getDepartments = () => apiRequest('/api/departments/');
