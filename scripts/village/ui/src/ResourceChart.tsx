import { GiniTimeseries } from './types';
import { RESOURCE_COLORS } from './colors';

interface Props {
  data: GiniTimeseries;
  width?: number;
  height?: number;
}

const RES_ORDER = ['coin', 'wood', 'stone', 'grain'];
const RES_COLORS_LINE = ['#ffd54f', '#a5d6a7', '#90a4ae', '#ffcc80'];

export default function ResourceChart({ data, width = 600, height = 260 }: Props) {
  const points = data.gini_timeseries;
  if (points.length < 2 || !points[0].resources) {
    return <div style={{ color: '#888', fontSize: 14, padding: 20, textAlign: 'center' }}>Need at least 2 epochs with resource data</div>;
  }

  const pad = { top: 28, right: 24, bottom: 36, left: 56 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;

  const epochs = points.map((p) => p.epoch);
  const minE = Math.min(...epochs);
  const maxE = Math.max(...epochs);

  const citizens = data.citizen_peer_ids;
  const allVals = points.flatMap((p) => {
    const res = p.resources!;
    return RES_ORDER.map((r) => citizens.reduce((s, c) => s + (res[c]?.[r] ?? 0), 0));
  });
  const maxV = Math.max(...allVals, 1);

  const xScale = (e: number) => pad.left + ((e - minE) / Math.max(1, maxE - minE)) * plotW;
  const yScale = (v: number) => pad.top + (1 - v / maxV) * plotH;

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 10 }}>
        <span style={{ fontSize: 14, fontWeight: 600, color: '#ccc' }}>Total resources (all citizens)</span>
        <span style={{ fontSize: 11, color: '#555' }}>stock per resource type over time</span>
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

        {RES_ORDER.map((r, ri) => {
          const vals = points.map((p) => {
            const res = p.resources!;
            return citizens.reduce((s, c) => s + (res[c]?.[r] ?? 0), 0);
          });
          const line = vals.map((v, i) => `${xScale(epochs[i])},${yScale(v)}`).join(' ');
          return (
            <g key={r}>
              <polyline points={line} fill="none" stroke={RES_COLORS_LINE[ri]} strokeWidth={2.5} strokeLinejoin="round" opacity={0.85} />
              {vals.map((v, i) => (
                <circle key={i} cx={xScale(epochs[i])} cy={yScale(v)} r={4} fill="#0d0d0d" stroke={RES_COLORS_LINE[ri]} strokeWidth={2} />
              ))}
            </g>
          );
        })}

        {RES_ORDER.map((r, i) => (
          <g key={r} transform={`translate(${pad.left + i * 80}, ${height - 2})`}>
            <rect x={0} y={-8} width={10} height={10} rx={2} fill={RES_COLORS_LINE[i]} />
            <text x={14} y={0} fill="#888" fontSize={9}>{r}</text>
          </g>
        ))}
      </svg>
    </div>
  );
}
