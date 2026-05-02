export interface EpochSnapshot {
  epoch: number;
  gini: number;
  policy_applied: { wealth_tax_rate: number; ubi: number };
  balances: Record<string, number>;
  pre_tax_balances: Record<string, number>;
  actions_log?: ActionEntry[];
}

export interface ActionEntry {
  citizen: string;
  slot: number;
  action: string;
  amount?: number;
  resource?: string;
  give_resource?: string;
  give?: number;
  want_resource?: string;
  want?: number;
  counterparty?: string;
  accepted?: boolean;
  outcome?: string;
  offer_id?: string;
  from?: string;
  executed?: boolean;
  why?: string;
}

export interface GiniTimeseries {
  run_id: string;
  max_epochs: number;
  actions_per_epoch: number;
  citizen_peer_ids: string[];
  gini_timeseries: EpochSnapshot[];
}
