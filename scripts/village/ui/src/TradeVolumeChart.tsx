import { GiniTimeseries } from './types';

interface Props {
  data: GiniTimeseries;
  width?: number;
  height?: number;
}

export default function TradeVolumeChart({ data, width = 600, height = 260 }: Props) {
  const points = data.gini_timeseries;
  if (points.length < 2) {
    return <div style={{ color: '#888', fontSize: 14, padding: 20, textAlign: 'center' }}>Need at least 2 epochs</div>;
  }

  const pad = { top: 28, right: 24, bottom: 36, left: 56 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;

  const epochs = points.map((p) => p.epoch);
  const minE = Math.min(...epochs);
  const maxE = Math.max(...epochs);

  const counts = points.map((snap) =>
    (snap.actions_log || []).filter((a) => a.action === 'trade_commit' && a.executed).length
  );
  const maxV = Math.max(...counts, 1);

  const xScale = (e: number) => pad.left + ((e - minE) / Math.max(1, maxE - minE)) * plotW;
  const yScale = (v: number) => pad.top + (1 - v / maxV) * plotH;

  const linePts = points.map((p, i) => `${xScale(p.epoch)},${yScale(counts[i])}`).join(' ');

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 10 }}>
        <span style={{ fontSize: 14, fontWeight: 600, color: '#ccc' }}>Executed trades</span>
        <span style={{ fontSize: 11, color: '#555' }}>per epoch</span>
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

        <polyline points={linePts} fill="none" stroke="#4fc3f7" strokeWidth={2.5} strokeLinejoin="round" />

        {points.map((p, i) => (
          <g key={i}>
            <circle cx={xScale(p.epoch)} cy={yScale(counts[i])} r={5} fill="#0d0d0d" stroke="#4fc3f7" strokeWidth={2} />
            <text x={xScale(p.epoch)} y={yScale(counts[i]) - 12} textAnchor="middle" fill="#4fc3f7" fontSize={12} fontWeight={600}>
              {counts[i]}
            </text>
          </g>
        ))}
      </svg>
    </div>
  );
}
