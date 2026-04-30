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
      <h1 style={{ margin: '0 0 8px 0' }}>AI Village Simulation</h1>

      <div style={{ marginBottom: 16 }}>
        <label style={{ marginRight: 8, fontWeight: 600 }}>Run:</label>
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
      </div>

      {error && <div style={{ color: '#f77', marginBottom: 12 }}>{error}</div>}

      {loading && <div style={{ color: '#888' }}>Loading…</div>}

      {data && (
        <>
          <div style={{ marginBottom: 12, fontSize: 13, color: '#aaa' }}>
            citizens: {data.citizen_peer_ids.length} | actions/epoch:{' '}
            {data.actions_per_epoch} | epochs: {data.max_epochs}
          </div>
          <GiniChart data={data} />
          <ActionsTable data={data} />
        </>
      )}
    </div>
  );
}

const container: React.CSSProperties = {
  maxWidth: 800,
  margin: '32px auto',
  padding: '0 16px',
  fontFamily: 'system-ui, sans-serif',
  color: '#eee',
};

const selectStyle: React.CSSProperties = {
  padding: '4px 8px',
  fontSize: 14,
  borderRadius: 4,
  border: '1px solid #555',
  background: '#222',
  color: '#eee',
  marginRight: 8,
};

const btnStyle: React.CSSProperties = {
  padding: '4px 12px',
  fontSize: 14,
  borderRadius: 4,
  border: '1px solid #555',
  background: '#333',
  color: '#eee',
  cursor: 'pointer',
};
