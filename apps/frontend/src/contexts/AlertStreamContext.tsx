import { createContext, useContext } from "react";
import type { AlertPayload } from "../hooks/useAlertStream";

interface AlertStreamContextValue {
  criticalQueue: AlertPayload[];
  recentAlerts: AlertPayload[];
  dequeueCritical: () => void;
}

const defaultValue: AlertStreamContextValue = {
  criticalQueue: [],
  recentAlerts: [],
  dequeueCritical: () => {},
};

/**
 * Provides the shared alert stream state (single WS connection) to the tree.
 * Provided by App.tsx; consumed by DashboardPage and FlashOverlay wiring.
 */
export const AlertStreamContext =
  createContext<AlertStreamContextValue>(defaultValue);

export function useAlertStreamContext(): AlertStreamContextValue {
  return useContext(AlertStreamContext);
}
