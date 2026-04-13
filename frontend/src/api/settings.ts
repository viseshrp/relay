import { apiRequest } from "@/api/client";
import type { HealthResponse, SystemStatusResponse, UserSettings } from "@/types/api";

export function getHealth() {
  return apiRequest<HealthResponse>("/health");
}

export function getSystemStatus() {
  return apiRequest<SystemStatusResponse>("/system/status");
}

export function getUserSettings() {
  return apiRequest<UserSettings>("/settings");
}

export function updateUserSettings(payload: Partial<UserSettings>) {
  return apiRequest<UserSettings>("/settings", { method: "PUT", body: JSON.stringify(payload) });
}
