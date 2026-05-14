export interface Route {
  origin: string;
  destination: string;
  /** "flexible" checks the next 14 days, or provide specific dates like ["2024-08-15"] */
  dates: "flexible" | string[];
  /** Alert if price is at or below this (0 = any Go Wild seat) */
  maxPrice?: number;
}

export interface NotifyConfig {
  email?: {
    enabled: boolean;
    smtp: {
      host: string;
      port: number;
      secure?: boolean;
      user: string;
      pass: string;
    };
    to: string;
  };
  pushover?: {
    enabled: boolean;
    userKey: string;
    apiToken: string;
  };
  slack?: {
    enabled: boolean;
    webhookUrl: string;
  };
  discord?: {
    enabled: boolean;
    webhookUrl: string;
  };
}

export interface Config {
  routes: Route[];
  /** Timezone for date calculations, e.g. "America/Chicago" */
  timezone?: string;
  notifications: NotifyConfig;
}

export interface GoWildFlight {
  origin: string;
  destination: string;
  date: string;
  departureTime: string;
  flightNumber: string;
  price: number;
  currency: string;
  fareClass: string;
}

export interface SeenState {
  [key: string]: number; // flightKey -> last seen timestamp
}
