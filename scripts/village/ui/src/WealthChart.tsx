import { GiniTimeseries } from './types';
import { CITIZEN_COLORS } from './colors';

interface Props {
  data: GiniTimeseries;
  width?: number;
  height?: number;
}

export default function WealthChart({ data, width = 600, height = 250 }: Props) {
  const points = data.gini_timeseries;
  const citizens = data.citizen_peer_ids;
  if (points.length < 2 || !points[0].wealth) {
    return (
      <div style={{ color: '#888', fontSize: 14, padding: 20, textAlign: 'center' }}>
        Need at least 2 epochs with wealth data
      </div>
    );
  }

  const pad = { top: 32, right: 24, bottom: 36, left: 56 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;

  const epochs = points.map((p) => p.epoch);
  const minE = Math.min(...epochs);
  const maxE = Math.max(...epochs);
  const allValues = points.flatMap((p) =>
    citizens.map((c) => (p.wealth?.[c] ?? 0))
  );
  const maxV = Math.max(...allValues, 1);

  const xScale = (e: number) => pad.left + ((e - minE) / Math.max(1, maxE - minE)) * plotW;
  const yScale = (v: number) => pad.top + (1 - v / maxV) * plotH;

  const yTicks = 5;

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 10 }}>
        <span style={{ fontSize: 14, fontWeight: 600, color: '#ccc' }}>Wealth over time</span>
        <span style={{ fontSize: 11, color: '#555' }}>
          Epoch {points[0].epoch} – {points[points.length - 1].epoch}
        </span>
      </div>
      <svg width={width} height={height} style={{ display: 'block' }}>
        {Array.from({ length: yTicks + 1 }, (_, i) => (maxV * i) / yTicks).map((v, i) => (
          <g key={i}>
            <line x1={pad.left} y1={yScale(v)} x2={width - pad.right} y2={yScale(v)} stroke="#222" strokeWidth={1} />
            <text x={pad.left - 8} y={yScale(v) + 4} textAnchor="end" fill="#666" fontSize={11}>
              {v.toFixed(0)}
            </text>
          </g>
        ))}
        {epochs.map((e) => (
          <text key={e} x={xScale(e)} y={height - pad.bottom + 18} textAnchor="middle" fill="#666" fontSize={11}>
            Epoch {e}
          </text>
        ))}
        <line x1={pad.left} y1={pad.top} x2={pad.left} y2={height - pad.bottom} stroke="#444" strokeWidth={1} />
        <line x1={pad.left} y1={height - pad.bottom} x2={width - pad.right} y2={height - pad.bottom} stroke="#444" strokeWidth={1} />

        {citizens.map((c, ci) => {
          const linePts = points.map((p) => `${xScale(p.epoch)},${yScale(p.wealth?.[c] ?? 0)}`).join(' ');
          return (
            <g key={c}>
              <polyline points={linePts} fill="none" stroke={CITIZEN_COLORS[ci % CITIZEN_COLORS.length]}
                strokeWidth={2} strokeLinejoin="round" opacity={0.85} />
              {points.map((p, pi) => (
                <circle key={pi} cx={xScale(p.epoch)} cy={yScale(p.wealth?.[c] ?? 0)}
                  r={3} fill={CITIZEN_COLORS[ci % CITIZEN_COLORS.length]} opacity={0.7} />
              ))}
            </g>
          );
        })}
      </svg>
    </div>
  );
}
