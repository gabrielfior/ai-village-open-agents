import { useState, useEffect, useCallback } from 'react';
import { GiniTimeseries } from './types';
import GiniChart from './GiniChart';
import ActionsTable from './ActionsTable';

const API = '/api';

export default function App() {
  const [runs, setRuns] = useState<string[]>([]);
  const [selected, setSelected] = useState('');
  const [data, setData] = useState<GiniTimeseries | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    fetch(`${API}/runs/`)
      .then((r) => r.json())
      .then((names) => {
        setRuns(names);
        if (names.length > 0) setSelected(names[0]);
      })
      .catch(() => setError('Could not load runs list. Make sure Docker infra is running.'));
  }, []);

  const loadRun = useCallback(async (runId: string) => {
    if (!runId) return;
    setLoading(true);
    setError('');
    try {
      const r = await fetch(`${API}/runs/${runId}/gini_timeseries.json`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const json: GiniTimeseries = await r.json();
      setData(json);
    } catch {
      setError(`Could not load gini_timeseries.json for "${runId}". Does the file exist?`);
      setData(null);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    if (selected) loadRun(selected);
  }, [selected, loadRun]);

  return (
    <div style={container}>
      <div style={headerBar}>
        <span style={{ fontSize: 20, fontWeight: 700 }}>AI Village Simulation</span>
        <span style={{ fontSize: 12, color: '#666' }}>simulation viewer</span>
      </div>

      <div style={toolbar}>
        <label style={{ marginRight: 8, fontWeight: 600, color: '#aaa', fontSize: 13 }}>
          Run:
        </label>
        <select
          value={selected}
          onChange={(e) => setSelected(e.target.value)}
          style={selectStyle}
        >
          {runs.length === 0 && <option value="">(no runs found)</option>}
          {runs.map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </select>
        <button onClick={() => loadRun(selected)} style={btnStyle}>
          Reload
        </button>
        {loading && <span style={{ marginLeft: 12, color: '#888', fontSize: 12 }}>Loading…</span>}
      </div>

      {error && (
        <div style={errorBar}>
          {error}
        </div>
      )}

      {data && (
        <>
          <div style={metaBar}>
            <span>{data.citizen_peer_ids.length} citizen(s)</span>
            <span>{data.actions_per_epoch} actions/epoch</span>
            <span>{data.max_epochs} epochs</span>
            <span style={{ color: '#888' }}>run: {data.run_id}</span>
          </div>
          <div style={{ background: '#111', borderRadius: 8, padding: 16, marginBottom: 24 }}>
            <GiniChart data={data} width={700} height={280} />
          </div>
          <ActionsTable data={data} />
        </>
      )}
    </div>
  );
}

const container: React.CSSProperties = {
  maxWidth: 850,
  margin: '0 auto',
  padding: '0 16px 64px',
  fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
  color: '#e0e0e0',
  background: '#0d0d0d',
  minHeight: '100vh',
};

const headerBar: React.CSSProperties = {
  display: 'flex',
  alignItems: 'baseline',
  gap: 12,
  padding: '20px 0 12px',
  borderBottom: '1px solid #222',
  marginBottom: 16,
};

const toolbar: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  marginBottom: 16,
};

const selectStyle: React.CSSProperties = {
  padding: '6px 10px',
  fontSize: 13,
  borderRadius: 6,
  border: '1px solid #444',
  background: '#1a1a1a',
  color: '#e0e0e0',
  marginRight: 8,
  outline: 'none',
  cursor: 'pointer',
  minWidth: 180,
};

const btnStyle: React.CSSProperties = {
  padding: '6px 14px',
  fontSize: 13,
  borderRadius: 6,
  border: '1px solid #555',
  background: '#2a2a2a',
  color: '#ccc',
  cursor: 'pointer',
  fontWeight: 500,
};

const errorBar: React.CSSProperties = {
  color: '#ef9a9a',
  marginBottom: 16,
  padding: '10px 14px',
  background: '#2a1010',
  borderRadius: 6,
  border: '1px solid #5a2020',
  fontSize: 13,
};

const metaBar: React.CSSProperties = {
  display: 'flex',
  gap: 16,
  marginBottom: 20,
  fontSize: 12,
  color: '#666',
  padding: '8px 0',
  borderBottom: '1px solid #222',
};
