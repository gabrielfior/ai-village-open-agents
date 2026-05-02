import { GiniTimeseries, ActionEntry } from './types';

interface Props {
  data: GiniTimeseries;
}

function shortPid(pid: string): string {
  return pid.length > 12 ? pid.slice(0, 12) + '…' : pid;
}

const CITIZEN_COLORS = ['#4fc3f7', '#ffb74d', '#81c784', '#e57373'];
const ACTION_COLORS: Record<string, string> = {
  earn: '#4caf50',
  trade_offer: '#ff9800',
  trade_commit: '#2196f3',
  trade_accept: '#26a69a',
  trade_prepare: '#9c27b0',
  noop: '#666',
  dummy: '#555',
};

function tagStyle(action: string): React.CSSProperties {
  const bg = ACTION_COLORS[action] || '#555';
  return {
    display: 'inline-block',
    background: bg,
    color: '#fff',
    padding: '1px 7px',
    borderRadius: 4,
    fontSize: 11,
    fontWeight: 600,
    fontFamily: 'monospace',
    textTransform: 'uppercase',
    letterSpacing: '0.3px',
  };
}

function actionDetail(a: ActionEntry) {
  if (a.action === 'earn') {
    return <span style={{ color: '#a5d6a7' }}>+{a.amount}</span>;
  }
  if (a.action === 'trade_offer') {
    const icon = a.accepted ? '✓' : '✗';
    const color = a.accepted ? '#a5d6a7' : '#ef9a9a';
    return (
      <span style={{ color: '#ccc' }}>
        → {shortPid(a.counterparty || '')}{' '}
        <span style={{ color: '#aaa' }}>g</span>
        <span style={{ color: '#ffb74d' }}>{a.give}</span>{' '}
        <span style={{ color: '#aaa' }}>w</span>
        <span style={{ color: '#ffb74d' }}>{a.want}</span>{' '}
        <span style={{ color }}>{icon}</span>
      </span>
    );
  }
  if (a.action === 'trade_prepare') {
    return (
      <span style={{ color: '#ccc' }}>
        → {shortPid(a.counterparty || '')}{' '}
        <span style={{ color: '#aaa' }}>g</span>
        <span style={{ color: '#ce93d8' }}>{a.give}</span>{' '}
        <span style={{ color: '#aaa' }}>w</span>
        <span style={{ color: '#ce93d8' }}>{a.want}</span>
      </span>
    );
  }
  if (a.action === 'trade_commit') {
    return <span style={{ color: '#90caf9' }}>offer {a.offer_id?.slice(0, 8) || ''}</span>;
  }
  if (a.action === 'trade_accept') {
    const ok = a.executed ? 'executed' : 'rejected';
    const color = a.executed ? '#a5d6a7' : '#ef9a9a';
    return (
      <span style={{ color: '#ccc' }}>
        ← {shortPid(a.from || '')}{' '}
        <span style={{ color: '#aaa' }}>take g</span>
        <span style={{ color: '#ffb74d' }}>{a.give}</span>{' '}
        <span style={{ color: '#aaa' }}>give w</span>
        <span style={{ color: '#ffb74d' }}>{a.want}</span>{' '}
        <span style={{ color }}>{ok}</span>
      </span>
    );
  }
  return null;
}

export default function ActionsTable({ data }: Props) {
  const citizenIds = data.citizen_peer_ids;

  return (
    <div>
      <h2 style={sectionTitle}>Actions per epoch</h2>
      {data.gini_timeseries.map((snap) => {
        const log = snap.actions_log || [];
        return (
          <div key={snap.epoch} style={{ marginBottom: 28 }}>
            <div style={epochHeader}>
              <span style={{ fontSize: 16, fontWeight: 700 }}>Epoch {snap.epoch}</span>
              <span style={{ marginLeft: 12, color: '#888', fontSize: 13 }}>
                {log.length} action{log.length !== 1 ? 's' : ''}
              </span>
            </div>

            {log.length > 0 ? (
              <table style={tableStyle}>
                <thead>
                  <tr>
                    <th style={thStyle}>#</th>
                    <th style={thStyle}>Citizen</th>
                    <th style={thStyle}>Action</th>
                    <th style={thStyle}>Details</th>
                  </tr>
                </thead>
                <tbody>
                  {log.map((a, i) => {
                    const colorIdx = citizenIds.indexOf(a.citizen);
                    const bg = i % 2 === 0 ? '#1a1a1a' : '#222';
                    return (
                      <tr key={i} style={{ background: bg }}>
                        <td style={{ ...tdStyle, color: '#666', width: 36, textAlign: 'center' }}>
                          {a.slot}
                        </td>
                        <td style={{ ...tdStyle, color: CITIZEN_COLORS[colorIdx] || '#aaa' }}>
                          {shortPid(a.citizen)}
                        </td>
                        <td style={tdStyle}>
                          <span style={tagStyle(a.action)}>{a.action}</span>
                        </td>
                        <td style={{ ...tdStyle, fontFamily: 'monospace', fontSize: 13 }}>
                          {actionDetail(a) || <span style={{ color: '#555' }}>—</span>}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            ) : (
              <p style={{ color: '#666', fontStyle: 'italic' }}>No action log available.</p>
            )}

            <div style={balanceBar}>
              {citizenIds.map((c, i) => {
                const pre = snap.pre_tax_balances[c] ?? 0;
                const post = snap.balances[c] ?? 0;
                const tax = pre - post + 5; // +ubi
                return (
                  <span key={c} style={{ marginRight: 20 }}>
                    <span style={{ color: CITIZEN_COLORS[i], fontWeight: 600 }}>
                      {shortPid(c)}
                    </span>
                    :{' '}
                    <span style={{ color: '#aaa' }}>{pre}</span>
                    {' → '}
                    <span style={{ color: '#eee', fontWeight: 600 }}>{post}</span>
                    <span style={{ color: '#666', fontSize: 12, marginLeft: 4 }}>
                      (tax:{' '}
                      {snap.policy_applied.wealth_tax_rate > 0
                        ? `${Math.round(pre * snap.policy_applied.wealth_tax_rate)}`
                        : '0'}
                      +ubi:{snap.policy_applied.ubi})
                    </span>
                  </span>
                );
              })}
              <span style={{ color: '#4fc3f7', fontWeight: 600 }}>
                Gini: {snap.gini.toFixed(4)}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

const sectionTitle: React.CSSProperties = {
  fontSize: 18,
  fontWeight: 700,
  margin: '32px 0 16px',
  borderBottom: '1px solid #333',
  paddingBottom: 8,
};

const epochHeader: React.CSSProperties = {
  padding: '8px 0',
  marginBottom: 8,
  borderBottom: '1px solid #2a2a2a',
};

const tableStyle: React.CSSProperties = {
  borderCollapse: 'collapse',
  width: '100%',
  fontSize: 13,
  borderRadius: 6,
  overflow: 'hidden',
};

const thStyle: React.CSSProperties = {
  border: '1px solid #333',
  padding: '6px 10px',
  background: '#111',
  color: '#888',
  textAlign: 'left',
  fontWeight: 600,
  fontSize: 11,
  textTransform: 'uppercase',
  letterSpacing: '0.5px',
};

const tdStyle: React.CSSProperties = {
  border: '1px solid #333',
  padding: '5px 10px',
  verticalAlign: 'middle',
};

const balanceBar: React.CSSProperties = {
  marginTop: 10,
  fontSize: 12,
  color: '#666',
  padding: '8px 10px',
  background: '#151515',
  borderRadius: 4,
  border: '1px solid #2a2a2a',
  display: 'flex',
  flexWrap: 'wrap',
  gap: '8px',
  alignItems: 'center',
};
