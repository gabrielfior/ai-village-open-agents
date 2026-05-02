import { GiniTimeseries } from './types';
import { CITIZEN_COLORS } from './colors';

interface Props {
  data: GiniTimeseries;
  width?: number;
  height?: number;
}

export default function BalanceChart({ data, width = 600, height = 260 }: Props) {
  const points = data.gini_timeseries;
  const citizens = data.citizen_peer_ids;
  if (points.length < 2) {
    return <div style={{ color: '#888', fontSize: 14, padding: 20, textAlign: 'center' }}>Need at least 2 epochs</div>;
  }

  const pad = { top: 28, right: 24, bottom: 36, left: 56 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;

  const epochs = points.map((p) => p.epoch);
  const minE = Math.min(...epochs);
  const maxE = Math.max(...epochs);
  const allVals = points.flatMap((p) => citizens.map((c) => p.balances[c] ?? 0));
  const maxV = Math.max(...allVals, 1);

  const xScale = (e: number) => pad.left + ((e - minE) / Math.max(1, maxE - minE)) * plotW;
  const yScale = (v: number) => pad.top + (1 - v / maxV) * plotH;

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 10 }}>
        <span style={{ fontSize: 14, fontWeight: 600, color: '#ccc' }}>Coin balance</span>
        <span style={{ fontSize: 11, color: '#555' }}>per citizen over time</span>
      </div>
      <svg width={width} height={height} style={{ display: 'block' }}>
        {[0, 0.25, 0.5, 0.75, 1].map((f, i) => {
          const v = maxV * f;
          return (
            <g key={i}>
              <line x1={pad.left} y1={yScale(v)} x2={width - pad.right} y2={yScale(v)} stroke="#222" strokeWidth={1} />
              <text x={pad.left - 8} y={yScale(v) + 4} textAnchor="end" fill="#666" fontSize={11}>{v.toFixed(0)}</text>
            </g>
          );
        })}
        {epochs.map((e) => (
          <text key={e} x={xScale(e)} y={height - pad.bottom + 18} textAnchor="middle" fill="#666" fontSize={11}>Epoch {e}</text>
        ))}
        <line x1={pad.left} y1={pad.top} x2={pad.left} y2={height - pad.bottom} stroke="#444" strokeWidth={1} />
        <line x1={pad.left} y1={height - pad.bottom} x2={width - pad.right} y2={height - pad.bottom} stroke="#444" strokeWidth={1} />

        {citizens.map((c, ci) => {
          const color = CITIZEN_COLORS[ci % CITIZEN_COLORS.length];
          const linePts = points.map((p) => `${xScale(p.epoch)},${yScale(p.balances[c] ?? 0)}`).join(' ');
          return (
            <g key={c}>
              <polyline points={linePts} fill="none" stroke={color} strokeWidth={2} strokeLinejoin="round" opacity={0.85} />
              {points.map((p, pi) => (
                <circle key={pi} cx={xScale(p.epoch)} cy={yScale(p.balances[c] ?? 0)} r={3} fill={color} opacity={0.7} />
              ))}
            </g>
          );
        })}

        {citizens.map((c, ci) => (
          <g key={c} transform={`translate(${pad.left + ci * 90}, ${height - 2})`}>
            <rect x={0} y={-8} width={10} height={10} rx={2} fill={CITIZEN_COLORS[ci % CITIZEN_COLORS.length]} />
            <text x={14} y={0} fill="#888" fontSize={9}>{c.slice(0, 8)}</text>
          </g>
        ))}
      </svg>
    </div>
  );
}
