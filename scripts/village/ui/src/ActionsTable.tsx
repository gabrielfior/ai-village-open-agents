import { GiniTimeseries, ActionEntry } from './types';

interface Props {
  data: GiniTimeseries;
}

function shortPid(pid: string): string {
  return pid.length > 12 ? pid.slice(0, 12) + '…' : pid;
}

function actionSummary(a: ActionEntry): string {
  if (a.action === 'earn') return `earn +${a.amount}`;
  if (a.action === 'trade_offer') {
    const ok = a.accepted ? '✓' : '✗';
    return `trade →${shortPid(a.counterparty || '')} give=${a.give} want=${a.want} ${ok}`;
  }
  if (a.action === 'noop') return 'noop';
  if (a.action === 'dummy') return 'dummy';
  return a.action;
}

export default function ActionsTable({ data }: Props) {
  const citizenIds = data.citizen_peer_ids;

  return (
    <div>
      <h2>Actions per epoch</h2>
      {data.gini_timeseries.map((snap) => (
        <div key={snap.epoch} style={{ marginBottom: 24 }}>
          <h3 style={{ margin: '8px 0' }}>Epoch {snap.epoch}</h3>

          {snap.actions_log && snap.actions_log.length > 0 ? (
            <table style={tableStyle}>
              <thead>
                <tr>
                  <th style={thStyle}>Citizen</th>
                  <th style={thStyle}>Slot</th>
                  <th style={thStyle}>Action</th>
                </tr>
              </thead>
              <tbody>
                {snap.actions_log.map((a, i) => (
                  <tr key={i}>
                    <td style={tdStyle}>{shortPid(a.citizen)}</td>
                    <td style={tdStyle}>{a.slot}</td>
                    <td style={tdStyle}>{actionSummary(a)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p style={{ color: '#888' }}>No action log available for this run type.</p>
          )}

          <div style={{ marginTop: 8, fontSize: 13, color: '#666' }}>
            <strong>Pre-tax:</strong>{' '}
            {citizenIds.map((c) => `${shortPid(c)}=${snap.pre_tax_balances[c] ?? '?'}`).join(', ')}
            {'  |  '}
            <strong>Post-tax+UBI:</strong>{' '}
            {citizenIds.map((c) => `${shortPid(c)}=${snap.balances[c] ?? '?'}`).join(', ')}
            {'  |  '}
            <strong>Gini:</strong> {snap.gini.toFixed(4)}
          </div>
        </div>
      ))}
    </div>
  );
}

const tableStyle: React.CSSProperties = {
  borderCollapse: 'collapse',
  width: '100%',
  fontSize: 13,
};
const thStyle: React.CSSProperties = {
  border: '1px solid #555',
  padding: '4px 8px',
  background: '#333',
  color: '#ccc',
  textAlign: 'left',
};
const tdStyle: React.CSSProperties = {
  border: '1px solid #444',
  padding: '4px 8px',
  fontFamily: 'monospace',
};
