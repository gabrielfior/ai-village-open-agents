import { GiniTimeseries } from './types';

interface Props {
  data: GiniTimeseries;
  width?: number;
  height?: number;
}

export default function PolicyChart({ data, width = 600, height = 260 }: Props) {
  const points = data.gini_timeseries;
  if (points.length < 2) {
    return <div style={{ color: '#888', fontSize: 14, padding: 20, textAlign: 'center' }}>Need at least 2 epochs</div>;
  }

  const pad = { top: 28, right: 56, bottom: 36, left: 56 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;

  const epochs = points.map((p) => p.epoch);
  const minE = Math.min(...epochs);
  const maxE = Math.max(...epochs);

  const taxes = points.map((p) => p.policy_applied.wealth_tax_rate);
  const ubis = points.map((p) => p.policy_applied.ubi);
  const maxTax = Math.max(...taxes, 0.01);
  const maxUbi = Math.max(...ubis, 1);

  const xScale = (e: number) => pad.left + ((e - minE) / Math.max(1, maxE - minE)) * plotW;
  const yScaleTax = (v: number) => pad.top + (1 - v / maxTax) * plotH;
  const yScaleUbi = (v: number) => pad.top + (1 - v / maxUbi) * plotH;

  const taxLine = points.map((p, i) => `${xScale(p.epoch)},${yScaleTax(taxes[i])}`).join(' ');
  const ubiLine = points.map((p, i) => `${xScale(p.epoch)},${yScaleUbi(ubis[i])}`).join(' ');

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 10 }}>
        <span style={{ fontSize: 14, fontWeight: 600, color: '#ccc' }}>Policy parameters</span>
        <span style={{ fontSize: 11, color: '#555' }}>tax rate (left) — UBI (right)</span>
      </div>
      <svg width={width} height={height} style={{ display: 'block' }}>
        {/* Tax grid (left axis) */}
        {[0, 0.25, 0.5, 0.75, 1].map((f, i) => {
          const v = maxTax * f;
          return (
            <g key={`t${i}`}>
              <line x1={pad.left} y1={yScaleTax(v)} x2={width - pad.right} y2={yScaleTax(v)} stroke="#222" strokeWidth={1} />
              <text x={pad.left - 8} y={yScaleTax(v) + 4} textAnchor="end" fill="#4fc3f7" fontSize={11}>
                {(v * 100).toFixed(0)}%
              </text>
            </g>
          );
        })}

        {/* UBI grid (right axis) */}
        {[0, 0.25, 0.5, 0.75, 1].map((f, i) => {
          const v = maxUbi * f;
          if (v === 0) return null;
          return (
            <text key={`u${i}`} x={width - pad.right + 8} y={yScaleUbi(v) + 4}
              textAnchor="start" fill="#ffb74d" fontSize={11}>
              {v.toFixed(0)}
            </text>
          );
        })}

        {epochs.map((e) => (
          <text key={e} x={xScale(e)} y={height - pad.bottom + 18} textAnchor="middle" fill="#666" fontSize={11}>Epoch {e}</text>
        ))}
        <line x1={pad.left} y1={pad.top} x2={pad.left} y2={height - pad.bottom} stroke="#444" strokeWidth={1} />
        <line x1={pad.left} y1={height - pad.bottom} x2={width - pad.right} y2={height - pad.bottom} stroke="#444" strokeWidth={1} />
        <line x1={width - pad.right} y1={pad.top} x2={width - pad.right} y2={height - pad.bottom} stroke="#333" strokeWidth={1} strokeDasharray="4,4" />

        {/* Tax line */}
        <polyline points={taxLine} fill="none" stroke="#4fc3f7" strokeWidth={2.5} strokeLinejoin="round" />
        {points.map((p, i) => (
          <circle key={`td${i}`} cx={xScale(p.epoch)} cy={yScaleTax(taxes[i])} r={4} fill="#0d0d0d" stroke="#4fc3f7" strokeWidth={2} />
        ))}
        {points.map((p, i) => (
          <text key={`tl${i}`} x={xScale(p.epoch)} y={yScaleTax(taxes[i]) - 10} textAnchor="middle" fill="#4fc3f7" fontSize={10} fontWeight={600}>
            {(taxes[i] * 100).toFixed(1)}%
          </text>
        ))}

        {/* UBI line */}
        <polyline points={ubiLine} fill="none" stroke="#ffb74d" strokeWidth={2.5} strokeLinejoin="round" strokeDasharray="6,3" />
        {points.map((p, i) => (
          <circle key={`ud${i}`} cx={xScale(p.epoch)} cy={yScaleUbi(ubis[i])} r={4} fill="#0d0d0d" stroke="#ffb74d" strokeWidth={2} />
        ))}
        {points.map((p, i) => (
          <text key={`ul${i}`} x={xScale(p.epoch)} y={yScaleUbi(ubis[i]) + 16} textAnchor="middle" fill="#ffb74d" fontSize={10} fontWeight={600}>
            {ubis[i]}
          </text>
        ))}

        {/* Legend */}
        <g transform={`translate(${pad.left}, ${height - 2})`}>
          <rect x={0} y={-8} width={10} height={10} rx={2} fill="#4fc3f7" />
          <text x={14} y={0} fill="#888" fontSize={9}>tax rate</text>
          <rect x={80} y={-8} width={10} height={10} rx={2} fill="#ffb74d" />
          <text x={94} y={0} fill="#888" fontSize={9}>UBI (coin)</text>
        </g>
      </svg>
    </div>
  );
}
