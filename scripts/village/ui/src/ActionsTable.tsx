import { useState } from 'react';
import { GiniTimeseries, ActionEntry } from './types';
import { CITIZEN_COLORS, RESOURCE_COLORS } from './colors';

interface Props {
  data: GiniTimeseries;
}

function shortPid(pid: string): string {
  return pid.length > 12 ? pid.slice(0, 12) + '…' : pid;
}

const ACTION_COLORS: Record<string, string> = {
  earn: '#4caf50', trade_offer: '#ff9800', trade_commit: '#2196f3',
  trade_accept: '#26a69a', trade_prepare: '#9c27b0', noop: '#666', dummy: '#555',
};

function tagStyle(action: string): React.CSSProperties {
  return {
    display: 'inline-block', background: ACTION_COLORS[action] || '#555',
    color: '#fff', padding: '1px 7px', borderRadius: 4,
    fontSize: 11, fontWeight: 600, fontFamily: 'monospace',
    textTransform: 'uppercase', letterSpacing: '0.3px',
  };
}

function Res({ r, v }: { r: string; v?: number }) {
  if (v === undefined || v === null) return null;
  return (
    <span style={{ color: RESOURCE_COLORS[r] || '#ccc', fontWeight: 600 }}>
      {r}:{v}
    </span>
  );
}

function actionSummary(a: ActionEntry) {
  if (a.action === 'earn') {
    return (
      <span>
        <Res r={a.resource || 'coin'} v={a.amount} />
      </span>
    );
  }
  if (a.action === 'trade_offer') {
    const icon = a.accepted ? '✓' : '✗';
    const color = a.accepted ? '#a5d6a7' : '#ef9a9a';
    return (
      <span>
        <span style={{ color: '#888' }}>→</span> {shortPid(a.counterparty || '')}{' '}
        <span style={{ color: '#888' }}>give</span> <Res r={a.give_resource || '?'} v={a.give} />
        {' '}
        <span style={{ color: '#888' }}>want</span> <Res r={a.want_resource || '?'} v={a.want} />
        {' '}<span style={{ color }}>{icon}</span>
      </span>
    );
  }
  if (a.action === 'trade_accept') {
    const ok = a.executed ? 'executed' : 'rejected';
    const color = a.executed ? '#a5d6a7' : '#ef9a9a';
    return (
      <span>
        <span style={{ color: '#888' }}>←</span> {shortPid(a.from || '')}{' '}
        <span style={{ color: '#888' }}>take</span> <Res r={a.give_resource || '?'} v={a.give} />
        {' '}
        <span style={{ color: '#888' }}>give</span> <Res r={a.want_resource || '?'} v={a.want} />
        {' '}<span style={{ color }}>{ok}</span>
      </span>
    );
  }
  if (a.action === 'trade_prepare') {
    return (
      <span>
        <span style={{ color: '#888' }}>→</span> {shortPid(a.counterparty || '')}{' '}
        <span style={{ color: '#888' }}>give</span> <Res r={a.give_resource || '?'} v={a.give} />
        {' '}
        <span style={{ color: '#888' }}>want</span> <Res r={a.want_resource || '?'} v={a.want} />
      </span>
    );
  }
  if (a.action === 'trade_commit') {
    return <span style={{ color: '#90caf9' }}>offer {a.offer_id?.slice(0, 8) || ''}</span>;
  }
  if (a.action === 'dummy') {
    return <span style={{ color: '#555' }}>{a.why || ''}</span>;
  }
  return null;
}

function detailRows(a: ActionEntry) {
  const rows: { label: string; value: string }[] = [];
  const push = (label: string, value: string) => rows.push({ label, value });
  push('action', a.action);
  push('slot', String(a.slot));
  push('citizen', a.citizen);

  if (a.resource) push('resource', a.resource);
  if (a.amount !== undefined) push('amount', String(a.amount));
  if (a.give_resource) push('give_resource', a.give_resource);
  if (a.give !== undefined) push('give_amount', String(a.give));
  if (a.want_resource) push('want_resource', a.want_resource);
  if (a.want !== undefined) push('want_amount', String(a.want));
  if (a.counterparty) push('counterparty', a.counterparty);
  if (a.from) push('from', a.from);
  if (a.offer_id) push('offer_id', a.offer_id);
  if (a.accepted !== undefined) push('accepted', String(a.accepted));
  if (a.executed !== undefined) push('executed', String(a.executed));
  if (a.outcome) push('outcome', a.outcome);
  if (a.why) push('why', a.why);

  return rows;
}

export default function ActionsTable({ data }: Props) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const toggle = (key: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });
  };

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
                    <th style={{ ...thStyle, width: 32 }}>#</th>
                    <th style={thStyle}>Citizen</th>
                    <th style={thStyle}>Action</th>
                    <th style={thStyle}>Details</th>
                  </tr>
                </thead>
                <tbody>
                  {log.map((a, i) => {
                    const key = `${snap.epoch}-${i}`;
                    const open = expanded.has(key);
                    const colorIdx = citizenIds.indexOf(a.citizen);
                    const bg = i % 2 === 0 ? '#1a1a1a' : '#222';
                    const details = detailRows(a);
                    return [
                      // action row
                      <tr key={key} style={{ background: bg, cursor: 'pointer' }}
                          onClick={() => toggle(key)}>
                        <td style={{ ...tdStyle, color: '#666', textAlign: 'center' }}>
                          {a.slot}{' '}
                          <span style={{ fontSize: 9, color: '#555' }}>
                            {open ? '▲' : '▼'}
                          </span>
                        </td>
                        <td style={{ ...tdStyle, color: CITIZEN_COLORS[colorIdx] || '#aaa' }}>
                          {shortPid(a.citizen)}
                        </td>
                        <td style={tdStyle}>
                          <span style={tagStyle(a.action)}>{a.action}</span>
                        </td>
                        <td style={{ ...tdStyle, fontFamily: 'monospace', fontSize: 13 }}>
                          {actionSummary(a) || <span style={{ color: '#555' }}>—</span>}
                        </td>
                      </tr>,
                      // detail row (only when expanded)
                      open ? (
                        <tr key={`${key}-d`} style={{ background: '#0a0a0a' }}>
                          <td colSpan={4} style={{ padding: 0, border: '1px solid #333', borderTop: 'none' }}>
                            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                              <tbody>
                                {details.map((r) => (
                                  <tr key={r.label}>
                                    <td style={{ ...detailTd, color: '#777', width: 140, paddingLeft: 36 }}>{r.label}</td>
                                    <td style={{ ...detailTd, fontFamily: 'monospace', wordBreak: 'break-all' }}>
                                      {r.label === 'citizen' || r.label === 'counterparty' || r.label === 'from' ? (
                                        <span style={{ color: CITIZEN_COLORS[citizenIds.indexOf(r.value)] || '#aaa' }}>
                                          {r.value}
                                        </span>
                                      ) : r.label === 'give_resource' || r.label === 'want_resource' || r.label === 'resource' ? (
                                        <span style={{ color: RESOURCE_COLORS[r.value] || '#ccc', fontWeight: 600 }}>
                                          {r.value}
                                        </span>
                                      ) : (
                                        r.value
                                      )}
                                    </td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </td>
                        </tr>
                      ) : null,
                    ];
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
                return (
                  <span key={c} style={{ marginRight: 20 }}>
                    <span style={{ color: CITIZEN_COLORS[i], fontWeight: 600 }}>{shortPid(c)}</span>
                    : <span style={{ color: '#aaa' }}>{pre}</span>
                    {' → '}
                    <span style={{ color: '#eee', fontWeight: 600 }}>{post}</span>
                  </span>
                );
              })}
              <span style={{ color: '#4fc3f7', fontWeight: 600 }}>Gini: {snap.gini.toFixed(4)}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

const sectionTitle: React.CSSProperties = {
  fontSize: 18, fontWeight: 700, margin: '32px 0 16px',
  borderBottom: '1px solid #333', paddingBottom: 8,
};
const epochHeader: React.CSSProperties = {
  padding: '8px 0', marginBottom: 8, borderBottom: '1px solid #2a2a2a',
};
const tableStyle: React.CSSProperties = {
  borderCollapse: 'collapse', width: '100%', fontSize: 13, borderRadius: 6, overflow: 'hidden',
};
const thStyle: React.CSSProperties = {
  border: '1px solid #333', padding: '6px 10px', background: '#111', color: '#888',
  textAlign: 'left', fontWeight: 600, fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.5px',
};
const tdStyle: React.CSSProperties = {
  border: '1px solid #333', padding: '5px 10px', verticalAlign: 'middle',
};
const detailPanel: React.CSSProperties = {
  background: '#0d0d0d', border: '1px solid #333', borderTop: 'none',
  padding: '6px 10px',
};
const detailTd: React.CSSProperties = {
  padding: '3px 10px', verticalAlign: 'top', borderBottom: '1px solid #1a1a1a',
};
const balanceBar: React.CSSProperties = {
  marginTop: 10, fontSize: 12, color: '#666',
  padding: '8px 10px', background: '#151515', borderRadius: 4,
  border: '1px solid #2a2a2a', display: 'flex', flexWrap: 'wrap',
  gap: '8px', alignItems: 'center',
};
