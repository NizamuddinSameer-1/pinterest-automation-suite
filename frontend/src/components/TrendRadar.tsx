import React, { useState, useEffect, useRef } from 'react';
import {
  api,
  TrendDossier,
  TrendProduct,
  PinterestOfficialTrendItem,
  TrendDeepDiveResponse,
  PopularPinItem,
} from '../api';
import {
  TrendingUp,
  Search,
  Sparkles,
  Flame,
  Zap,
  ShoppingBag,
  ExternalLink,
  ArrowRight,
  RefreshCw,
  FolderPlus,
  Compass,
  CheckCircle2,
  AlertCircle,
  Loader2,
  Star,
  Clock,
  Palette,
  Layers,
  Activity,
  Copy,
  Check,
  X,
  ChevronRight,
  BookmarkPlus,
} from 'lucide-react';

interface TrendRadarProps {
  setActiveTab?: (tab: string) => void;
  setSelectedJobId?: (id: string) => void;
  setSelectedProductId?: (id: string) => void;
}

const COMMERCIAL_CATEGORIES = [
  { id: 'all', label: 'All Signals' },
  { id: 'fashion', label: '👗 Fashion & Outfits' },
  { id: 'home', label: '🏡 Home Decor' },
  { id: 'kitchen', label: '☕ Kitchen & Lifestyle' },
  { id: 'tech', label: '💻 Tech & Desk' },
  { id: 'seasonal', label: '🌸 Seasonal 2026' },
];

const PINTEREST_PRESETS = [
  { id: 'breakout', label: '🔥 Seasonal Surges (Rising Now)', icon: Flame },
  { id: 'growing', label: '📈 Growing Trends', icon: TrendingUp },
  { id: 'top', label: '⭐ Top Overall', icon: Star },
];

const PINTEREST_INTENTS = [
  { id: 'all', label: '🌟 All Signals' },
  { id: 'viral_blog', label: '💅 Viral Inspo / Blog (Nails, Hair, Outfits)' },
  { id: 'commercial_product', label: '🛍️ Physical Products' },
];

/** SVG Sparkline graph renderer for 52-week search momentum */
const SparklineGraph: React.FC<{
  data: number[];
  color?: string;
  height?: number;
  width?: number;
  showPoints?: boolean;
}> = ({ data, color = '#ec4899', height = 48, width = 160, showPoints = true }) => {
  if (!data || data.length < 2) {
    return (
      <div style={{ height, width, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)', fontSize: '0.72rem' }}>
        No curve data
      </div>
    );
  }

  const min = Math.min(...data);
  const max = Math.max(...data, 1);
  const range = max - min || 1;
  const paddingX = 4;
  const paddingY = 4;
  const innerH = height - paddingY * 2;
  const innerW = width - paddingX * 2;

  const points = data.map((val, idx) => {
    const x = paddingX + (idx / (data.length - 1)) * innerW;
    const y = height - paddingY - ((val - min) / range) * innerH;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });

  const pathD = `M ${points.join(' L ')}`;
  const areaD = `${pathD} L ${width - paddingX},${height} L ${paddingX},${height} Z`;
  const gradId = `spark-grad-${color.replace('#', '')}-${data.length}`;

  const lastPoint = points[points.length - 1].split(',');

  return (
    <svg width={width} height={height} style={{ overflow: 'visible', display: 'block' }}>
      <defs>
        <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.4" />
          <stop offset="100%" stopColor={color} stopOpacity="0.0" />
        </linearGradient>
      </defs>
      <path d={areaD} fill={`url(#${gradId})`} />
      <path d={pathD} fill="none" stroke={color} strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
      {showPoints && (
        <circle
          cx={lastPoint[0]}
          cy={lastPoint[1]}
          r="3.5"
          fill={color}
          stroke="#fff"
          strokeWidth="1.5"
        />
      )}
    </svg>
  );
};

/** Large 0–100 Normalized Search Momentum Graph for the Deep-Dive Drawer */
const LargeTrajectoryGraph: React.FC<{
  data: number[];
  dates?: string[];
  color?: string;
  height?: number;
}> = ({
  data,
  dates = ['Jun 2026', 'Jul 2026', 'Aug 2026', 'Sep 2026'],
  color = '#e60023',
  height = 150,
}) => {
  if (!data || data.length < 2) {
    return (
      <div style={{ height, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)' }}>
        No trajectory data
      </div>
    );
  }

  const max = 100;
  const paddingX = 28;
  const paddingY = 22;
  const innerH = height - paddingY * 2;
  const width = 640;
  const innerW = width - paddingX * 2;

  const points = data.map((val, idx) => {
    const clamped = Math.max(0, Math.min(100, val));
    const x = paddingX + (idx / (data.length - 1)) * innerW;
    const y = height - paddingY - (clamped / max) * innerH;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });

  const pathD = `M ${points.join(' L ')}`;
  const areaD = `${pathD} L ${width - paddingX},${height - paddingY} L ${paddingX},${height - paddingY} Z`;
  const gradId = `large-traj-grad-${Math.random().toString(36).slice(2, 7)}`;
  const lastPointCoords = points[points.length - 1].split(',');

  return (
    <div style={{ width: '100%', position: 'relative' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
        <span style={{ fontSize: '0.74rem', color: 'var(--text-muted)', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.04em' }}>
          Indexed from 0–100
        </span>
        <span style={{ fontSize: '0.74rem', color: '#ff6b81', fontWeight: 800 }}>
          Peak Volume: {data[data.length - 1]}/100
        </span>
      </div>

      <div style={{ position: 'relative', background: 'rgba(10, 14, 20, 0.75)', borderRadius: '12px', border: '1px solid var(--border-subtle)', padding: '14px 12px 10px 12px' }}>
        <svg viewBox={`0 0 ${width} ${height}`} style={{ width: '100%', height: 'auto', display: 'block', overflow: 'visible' }}>
          <defs>
            <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity="0.45" />
              <stop offset="80%" stopColor={color} stopOpacity="0.05" />
              <stop offset="100%" stopColor={color} stopOpacity="0.0" />
            </linearGradient>
          </defs>

          {/* Grid lines: 25, 50, 75, 100 */}
          {[25, 50, 75, 100].map((level) => {
            const y = height - paddingY - (level / 100) * innerH;
            return (
              <g key={level}>
                <line
                  x1={paddingX}
                  y1={y}
                  x2={width - paddingX}
                  y2={y}
                  stroke="rgba(255, 255, 255, 0.08)"
                  strokeDasharray="4 4"
                  strokeWidth="1"
                />
                <text
                  x={paddingX - 6}
                  y={y + 3}
                  textAnchor="end"
                  fill="rgba(255, 255, 255, 0.3)"
                  fontSize="9"
                  fontWeight="600"
                >
                  {level}
                </text>
              </g>
            );
          })}

          {/* Area under curve */}
          <path d={areaD} fill={`url(#${gradId})`} />

          {/* Line curve */}
          <path
            d={pathD}
            fill="none"
            stroke={color}
            strokeWidth="3.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />

          {/* Glowing Surge Point */}
          <circle
            cx={lastPointCoords[0]}
            cy={lastPointCoords[1]}
            r="5.5"
            fill={color}
            stroke="#fff"
            strokeWidth="2.5"
          />
          <circle
            cx={lastPointCoords[0]}
            cy={lastPointCoords[1]}
            r="12"
            fill={color}
            opacity="0.3"
          />
        </svg>

        {/* X-Axis Date Marks */}
        <div style={{
          display: 'flex',
          justifyContent: 'space-between',
          paddingLeft: '28px',
          paddingRight: '28px',
          marginTop: '6px',
        }}>
          {dates.map((d, i) => (
            <span key={i} style={{ fontSize: '0.74rem', color: 'var(--text-muted)', fontWeight: 600 }}>
              {d}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
};

/** Deep-Dive Slide-Over Drawer for Pinterest Trends */
const TrendDeepDiveDrawer: React.FC<{
  isOpen: boolean;
  onClose: () => void;
  term: string;
  data: TrendDeepDiveResponse | null;
  loading: boolean;
  onSelectKeyword: (keyword: string) => void;
  onImportPinReference: (pin: PopularPinItem, term: string, category: string) => void;
  onLaunchInspo: (term: string, category: string, previewUrl?: string) => void;
  importingPinId: string | null;
  importedPinIds: Set<string>;
  launchingInspoTerm: string | null;
  copiedKeywords: boolean;
  onCopyKeywords: (keywords: string[]) => void;
}> = ({
  isOpen,
  onClose,
  term,
  data,
  loading,
  onSelectKeyword,
  onImportPinReference,
  onLaunchInspo,
  importingPinId,
  importedPinIds,
  launchingInspoTerm,
  copiedKeywords,
  onCopyKeywords,
}) => {
  if (!isOpen) return null;

  return (
    <div
      onClick={onClose}
      style={{
        position: 'fixed',
        inset: 0,
        backgroundColor: 'rgba(5, 8, 14, 0.78)',
        backdropFilter: 'blur(10px)',
        zIndex: 9999,
        display: 'flex',
        justifyContent: 'flex-end',
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width: 'min(860px, 94vw)',
          height: '100%',
          backgroundColor: '#0d1117',
          borderLeft: '1px solid rgba(255, 255, 255, 0.12)',
          boxShadow: '-12px 0 40px rgba(0, 0, 0, 0.75)',
          overflowY: 'auto',
          display: 'flex',
          flexDirection: 'column',
          position: 'relative',
        }}
      >
        {/* Drawer Header */}
        <div
          style={{
            position: 'sticky',
            top: 0,
            zIndex: 20,
            background: 'rgba(13, 17, 23, 0.94)',
            backdropFilter: 'blur(12px)',
            borderBottom: '1px solid var(--border-subtle)',
            padding: '18px 24px',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            gap: '16px',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <div
              style={{
                width: '36px',
                height: '36px',
                borderRadius: '10px',
                background: 'linear-gradient(135deg, #e60023, #ff4757)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                boxShadow: '0 4px 14px rgba(230, 0, 35, 0.4)',
              }}
            >
              <Sparkles size={18} color="#fff" />
            </div>
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span
                  style={{
                    fontSize: '0.68rem',
                    color: '#ff6b81',
                    background: 'rgba(230, 0, 35, 0.15)',
                    padding: '2px 8px',
                    borderRadius: '6px',
                    fontWeight: 800,
                    letterSpacing: '0.04em',
                    textTransform: 'uppercase',
                  }}
                >
                  {data?.category || 'Pinterest Trend'}
                </span>
                <span style={{ fontSize: '0.74rem', color: 'var(--text-muted)' }}>
                  trends.pinterest.com
                </span>
              </div>
              <h2
                style={{
                  fontSize: '1.45rem',
                  fontWeight: 800,
                  margin: '4px 0 0 0',
                  color: '#fff',
                  lineHeight: 1.2,
                }}
              >
                {term}
              </h2>
            </div>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            {data && (
              <span
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '4px',
                  padding: '6px 12px',
                  borderRadius: '9999px',
                  fontSize: '0.8rem',
                  fontWeight: 800,
                  background: 'rgba(239, 68, 68, 0.18)',
                  border: '1px solid rgba(239, 68, 68, 0.45)',
                  color: '#f87171',
                }}
              >
                <Flame size={14} />
                vs. last month ↑ {data.mom_change > 0 ? `+${data.mom_change.toLocaleString()}%` : `${data.mom_change}%`}
              </span>
            )}
            <button
              onClick={onClose}
              style={{
                width: '36px',
                height: '36px',
                borderRadius: '8px',
                background: 'rgba(255, 255, 255, 0.06)',
                border: '1px solid var(--border-subtle)',
                color: 'var(--text-secondary)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                cursor: 'pointer',
                transition: 'all 0.15s ease',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.background = 'rgba(255, 255, 255, 0.15)';
                e.currentTarget.style.color = '#fff';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.background = 'rgba(255, 255, 255, 0.06)';
                e.currentTarget.style.color = 'var(--text-secondary)';
              }}
            >
              <X size={18} />
            </button>
          </div>
        </div>

        {/* Drawer Body */}
        <div style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '26px' }}>
          {loading ? (
            <div
              style={{
                padding: '100px 0',
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '16px',
              }}
            >
              <Loader2 size={36} color="#e60023" className="animate-spin" />
              <span style={{ fontSize: '0.94rem', color: 'var(--text-secondary)', fontWeight: 600 }}>
                Retrieving official 52-week search momentum & popular pins for "{term}"...
              </span>
            </div>
          ) : !data ? (
            <div style={{ padding: '60px 0', textAlign: 'center', color: 'var(--text-muted)' }}>
              Could not load trend deep dive details.
            </div>
          ) : (
            <>
              {/* Narrative description quote (Screenshot 1) */}
              <div
                style={{
                  background: 'linear-gradient(135deg, rgba(230, 0, 35, 0.08) 0%, rgba(168, 85, 247, 0.06) 100%)',
                  border: '1px solid rgba(230, 0, 35, 0.25)',
                  borderRadius: '14px',
                  padding: '20px 22px',
                  position: 'relative',
                }}
              >
                <div style={{ fontSize: '0.96rem', color: '#e2e8f0', lineHeight: 1.6, fontStyle: 'italic' }}>
                  "{data.description}"
                </div>
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    marginTop: '12px',
                    paddingTop: '10px',
                    borderTop: '1px solid rgba(255, 255, 255, 0.07)',
                    fontSize: '0.78rem',
                    color: 'var(--text-muted)',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <FolderPlus size={14} color="#38bdf8" />
                    <span style={{ color: '#38bdf8', fontWeight: 600 }}>
                      Recommended Board: {data.recommended_board}
                    </span>
                  </div>
                  <span style={{ color: '#a855f7', fontWeight: 600 }}>
                    {data.monetization_angle}
                  </span>
                </div>
              </div>

              {/* 52-Week Search Trajectory Curve (0-100 indexed) */}
              <div
                style={{
                  background: 'rgba(22, 27, 34, 0.75)',
                  border: '1px solid var(--border-subtle)',
                  borderRadius: '14px',
                  padding: '20px',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '14px',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <div>
                    <h3 style={{ fontSize: '1.05rem', fontWeight: 800, margin: 0, color: '#fff' }}>
                      Search Momentum Curve
                    </h3>
                    <p style={{ fontSize: '0.76rem', color: 'var(--text-secondary)', margin: '3px 0 0 0' }}>
                      Official Pinterest interest index across 52 weeks
                    </p>
                  </div>
                  <div style={{ display: 'flex', gap: '8px' }}>
                    <span
                      style={{
                        padding: '4px 10px',
                        borderRadius: '6px',
                        background: 'rgba(16, 185, 129, 0.15)',
                        border: '1px solid rgba(16, 185, 129, 0.35)',
                        color: '#34d399',
                        fontSize: '0.74rem',
                        fontWeight: 700,
                        display: 'flex',
                        alignItems: 'center',
                        gap: '4px',
                      }}
                    >
                      <TrendingUp size={12} />
                      +{data.wow_change}% WoW
                    </span>
                  </div>
                </div>

                <LargeTrajectoryGraph
                  data={data.sparkline}
                  dates={data.timeline_dates}
                  color={data.mom_change > 200 ? '#e60023' : '#a855f7'}
                  height={150}
                />
              </div>

              {/* 20-Day Early-Pinning Indexing Buffer Warning */}
              {data.indexing_window && (
                <div
                  style={{
                    background: 'rgba(249, 115, 22, 0.12)',
                    border: '1px solid rgba(249, 115, 22, 0.35)',
                    borderRadius: '12px',
                    padding: '14px 18px',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    flexWrap: 'wrap',
                    gap: '12px',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                    <Clock size={20} color="#fb923c" />
                    <div>
                      <div style={{ fontSize: '0.88rem', fontWeight: 800, color: '#fb923c' }}>
                        {data.indexing_window.advice}
                      </div>
                      <div style={{ fontSize: '0.76rem', color: 'var(--text-secondary)', marginTop: '2px' }}>
                        Pinterest requires 15–30 days to index and rank new pins. Publish this week to rank at peak volume.
                      </div>
                    </div>
                  </div>
                  <button
                    onClick={() => onLaunchInspo(data.term, data.category, data.popular_pins?.[0]?.image_url)}
                    disabled={launchingInspoTerm === data.term}
                    className="btn btn-primary"
                    style={{
                      padding: '7px 14px',
                      fontSize: '0.78rem',
                      fontWeight: 700,
                      display: 'flex',
                      alignItems: 'center',
                      gap: '6px',
                      background: 'linear-gradient(135deg, #e60023, #a855f7)',
                    }}
                  >
                    <Sparkles size={13} />
                    <span>Launch 20-Day Early Pin</span>
                  </button>
                </div>
              )}

              {/* Commonly Searched For (Screenshot 3) */}
              {data.commonly_searched_for && data.commonly_searched_for.length > 0 && (
                <div
                  style={{
                    background: 'rgba(22, 27, 34, 0.75)',
                    border: '1px solid var(--border-subtle)',
                    borderRadius: '14px',
                    padding: '20px',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '14px',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '10px' }}>
                    <div>
                      <h3 style={{ fontSize: '1.05rem', fontWeight: 800, margin: 0, color: '#fff' }}>
                        Pinners engaging with this trend commonly search for:
                      </h3>
                      <p style={{ fontSize: '0.76rem', color: 'var(--text-secondary)', margin: '3px 0 0 0' }}>
                        Click any keyword to pivot the deep-dive radar or copy all for your pin description SEO
                      </p>
                    </div>

                    <button
                      onClick={() => onCopyKeywords(data.commonly_searched_for)}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '6px',
                        padding: '6px 14px',
                        borderRadius: '8px',
                        background: copiedKeywords ? 'rgba(16, 185, 129, 0.2)' : 'rgba(255, 255, 255, 0.08)',
                        border: copiedKeywords ? '1px solid rgba(16, 185, 129, 0.45)' : '1px solid var(--border-subtle)',
                        color: copiedKeywords ? '#34d399' : '#e2e8f0',
                        fontSize: '0.78rem',
                        fontWeight: 700,
                        cursor: 'pointer',
                        transition: 'all 0.15s ease',
                      }}
                    >
                      {copiedKeywords ? (
                        <>
                          <Check size={14} />
                          <span>Copied All Keywords!</span>
                        </>
                      ) : (
                        <>
                          <Copy size={14} />
                          <span>Copy All Keywords (📋)</span>
                        </>
                      )}
                    </button>
                  </div>

                  {/* Pills cluster */}
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                    {data.commonly_searched_for.map((queryTag) => (
                      <button
                        key={queryTag}
                        onClick={() => onSelectKeyword(queryTag)}
                        style={{
                          display: 'inline-flex',
                          alignItems: 'center',
                          gap: '6px',
                          padding: '7px 14px',
                          borderRadius: '9999px',
                          background: 'rgba(255, 255, 255, 0.05)',
                          border: '1px solid rgba(255, 255, 255, 0.12)',
                          color: '#f1f5f9',
                          fontSize: '0.82rem',
                          fontWeight: 600,
                          cursor: 'pointer',
                          transition: 'all 0.15s ease',
                        }}
                        onMouseEnter={(e) => {
                          e.currentTarget.style.background = 'rgba(230, 0, 35, 0.15)';
                          e.currentTarget.style.borderColor = 'rgba(230, 0, 35, 0.4)';
                          e.currentTarget.style.color = '#ff6b81';
                          e.currentTarget.style.transform = 'translateY(-1px)';
                        }}
                        onMouseLeave={(e) => {
                          e.currentTarget.style.background = 'rgba(255, 255, 255, 0.05)';
                          e.currentTarget.style.borderColor = 'rgba(255, 255, 255, 0.12)';
                          e.currentTarget.style.color = '#f1f5f9';
                          e.currentTarget.style.transform = 'translateY(0)';
                        }}
                      >
                        <span>{queryTag}</span>
                        <ChevronRight size={13} color="rgba(255, 255, 255, 0.4)" />
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* Popular Pins Gallery (Screenshots 1 & 2) */}
              <div
                style={{
                  background: 'rgba(22, 27, 34, 0.75)',
                  border: '1px solid var(--border-subtle)',
                  borderRadius: '14px',
                  padding: '20px',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '16px',
                }}
              >
                <div>
                  <span style={{ fontSize: '0.74rem', color: '#ff6b81', fontWeight: 800, textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                    Browse popular Pins based on your keywords
                  </span>
                  <h3 style={{ fontSize: '1.25rem', fontWeight: 800, margin: '2px 0 0 0', color: '#fff' }}>
                    Popular Pins
                  </h3>
                </div>

                <div
                  style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(auto-fill, minmax(230px, 1fr))',
                    gap: '16px',
                  }}
                >
                  {data.popular_pins && data.popular_pins.map((pin) => {
                    const isImported = importedPinIds.has(pin.pin_id);
                    const isImporting = importingPinId === pin.pin_id;

                    return (
                      <div
                        key={pin.pin_id}
                        style={{
                          background: 'rgba(13, 17, 23, 0.85)',
                          border: isImported ? '1px solid rgba(16, 185, 129, 0.45)' : '1px solid var(--border-subtle)',
                          borderRadius: '12px',
                          overflow: 'hidden',
                          display: 'flex',
                          flexDirection: 'column',
                          justifyContent: 'space-between',
                          boxShadow: '0 4px 16px rgba(0, 0, 0, 0.35)',
                          transition: 'transform 0.15s ease, border-color 0.15s ease',
                        }}
                      >
                        {/* Pin Image Container — Clicking redirects to Pinterest search for that trend */}
                        <a
                          href={pin.pin_url || `https://www.pinterest.com/search/pins/?q=${encodeURIComponent(term)}`}
                          target="_blank"
                          rel="noreferrer"
                          title={`Search "${term}" on Pinterest`}
                          style={{
                            position: 'relative',
                            width: '100%',
                            height: '300px',
                            backgroundColor: '#000',
                            display: 'block',
                            cursor: 'pointer',
                          }}
                        >
                          <img
                            src={pin.image_url}
                            alt={pin.title}
                            style={{
                              width: '100%',
                              height: '100%',
                              objectFit: 'cover',
                              display: 'block',
                            }}
                            onError={(e) => {
                              const target = e.currentTarget as HTMLImageElement;
                              if (!target.dataset.hasFallback) {
                                target.dataset.hasFallback = 'true';
                                const fallbackList = [
                                  'https://images.unsplash.com/photo-1544441893-675973e31985?w=736&q=85',
                                  'https://images.unsplash.com/photo-1591047139829-d91aecb6caea?w=736&q=85',
                                  'https://images.unsplash.com/photo-1490481651871-ab68de25d43d?w=736&q=85',
                                  'https://images.unsplash.com/photo-1632345031435-8727f6897d53?w=736&q=85',
                                  'https://images.unsplash.com/photo-1522337360788-8b13dee7a37e?w=736&q=85',
                                  'https://images.unsplash.com/photo-1509198397868-475647b2a1e5?w=736&q=85',
                                  'https://images.unsplash.com/photo-1604654894610-df63bc536371?w=736&q=85',
                                  'https://images.unsplash.com/photo-1485230895905-ec40ba36b9bc?w=736&q=85',
                                ];
                                const hash = (pin.pin_id || '').split('').reduce((acc, char) => acc + char.charCodeAt(0), 0);
                                target.src = fallbackList[Math.abs(hash) % fallbackList.length];
                              }
                            }}
                          />

                          {/* Bold Text Overlay Banner (Screenshot 1 & 2) */}
                          {(pin.visual_hook || pin.overlay_text) && (
                            <div
                              style={{
                                position: 'absolute',
                                top: '12px',
                                left: '10px',
                                right: '10px',
                                background: 'rgba(15, 20, 30, 0.88)',
                                backdropFilter: 'blur(8px)',
                                border: '1px solid rgba(255, 255, 255, 0.18)',
                                borderRadius: '8px',
                                padding: '6px 10px',
                                textAlign: 'center',
                                boxShadow: '0 4px 14px rgba(0, 0, 0, 0.5)',
                              }}
                            >
                              <span
                                style={{
                                  fontSize: '0.74rem',
                                  fontWeight: 900,
                                  color: '#fff',
                                  letterSpacing: '0.04em',
                                  textTransform: 'uppercase',
                                }}
                              >
                                {pin.visual_hook || pin.overlay_text}
                              </span>
                            </div>
                          )}

                          {/* Top-Right Pinterest External Link */}
                          <div
                            title="Open search on Pinterest"
                            style={{
                              position: 'absolute',
                              bottom: '10px',
                              right: '10px',
                              width: '30px',
                              height: '30px',
                              borderRadius: '50%',
                              background: 'rgba(0, 0, 0, 0.75)',
                              border: '1px solid rgba(255, 255, 255, 0.25)',
                              color: '#fff',
                              display: 'flex',
                              alignItems: 'center',
                              justifyContent: 'center',
                              backdropFilter: 'blur(4px)',
                            }}
                          >
                            <ExternalLink size={13} />
                          </div>
                        </a>

                        {/* Pin Meta & Actions */}
                        <div style={{ padding: '12px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
                          <p
                            style={{
                              fontSize: '0.78rem',
                              color: '#cbd5e1',
                              margin: 0,
                              fontWeight: 600,
                              lineHeight: 1.4,
                              display: '-webkit-box',
                              WebkitLineClamp: 2,
                              WebkitBoxOrient: 'vertical',
                              overflow: 'hidden',
                            }}
                          >
                            {pin.title}
                          </p>

                          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                            {/* 1-Click Import as Style Reference */}
                            <button
                              onClick={() => onImportPinReference(pin, data.term, data.category)}
                              disabled={isImporting || isImported}
                              style={{
                                width: '100%',
                                padding: '7px 10px',
                                borderRadius: '8px',
                                fontSize: '0.75rem',
                                fontWeight: 700,
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'center',
                                gap: '6px',
                                cursor: isImported ? 'default' : 'pointer',
                                background: isImported
                                  ? 'rgba(16, 185, 129, 0.2)'
                                  : 'rgba(168, 85, 247, 0.15)',
                                border: isImported
                                  ? '1px solid rgba(16, 185, 129, 0.4)'
                                  : '1px solid rgba(168, 85, 247, 0.35)',
                                color: isImported ? '#34d399' : '#c084fc',
                                transition: 'all 0.15s ease',
                              }}
                            >
                              {isImporting ? (
                                <>
                                  <Loader2 size={13} className="animate-spin" />
                                  <span>Extracting Visual DNA...</span>
                                </>
                              ) : isImported ? (
                                <>
                                  <Check size={13} />
                                  <span>In Reference Library ✓</span>
                                </>
                              ) : (
                                <>
                                  <Palette size={13} />
                                  <span>Use as Style Reference</span>
                                </>
                              )}
                            </button>

                            {/* 1-Click Launch Inspo Pin Draft */}
                            <button
                              onClick={() => onLaunchInspo(data.term, data.category, pin.image_url)}
                              disabled={launchingInspoTerm === data.term}
                              className="btn btn-primary"
                              style={{
                                width: '100%',
                                padding: '6px 10px',
                                fontSize: '0.74rem',
                                fontWeight: 700,
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'center',
                                gap: '5px',
                                background: 'linear-gradient(135deg, #e60023, #a855f7)',
                              }}
                            >
                              <Sparkles size={12} />
                              <span>1-Click Launch Inspo Pin</span>
                            </button>
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>

                {/* Active search query indicator matching official Pinterest Trends */}
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '8px',
                    padding: '8px 4px 0 4px',
                  }}
                >
                  <span
                    style={{
                      width: '9px',
                      height: '9px',
                      borderRadius: '50%',
                      backgroundColor: '#38bdf8',
                      boxShadow: '0 0 8px rgba(56, 189, 248, 0.6)',
                      display: 'inline-block',
                      flexShrink: 0,
                    }}
                  />
                  <a
                    href={`https://www.pinterest.com/search/pins/?q=${encodeURIComponent(term)}`}
                    target="_blank"
                    rel="noreferrer"
                    style={{
                      fontSize: '0.86rem',
                      fontWeight: 700,
                      color: '#e2e8f0',
                      textDecoration: 'none',
                    }}
                    title={`View "${term}" on Pinterest search`}
                  >
                    {term}
                  </a>
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
};

export const TrendRadar: React.FC<TrendRadarProps> = ({
  setActiveTab,
  setSelectedJobId,
  setSelectedProductId,
}) => {
  // Mode: 'pinterest' (Official Pinterest Trends live scraper) vs 'commercial' (Amazon + Google Shopping)
  const [radarMode, setRadarMode] = useState<'pinterest' | 'commercial'>('pinterest');

  // ── Official Pinterest Trends State ──────────
  const [pinterestTrends, setPinterestTrends] = useState<PinterestOfficialTrendItem[]>([]);
  const [pinterestPreset, setPinterestPreset] = useState<string>('breakout');
  const [pinterestIntent, setPinterestIntent] = useState<string>('all');
  const [customPinterestTrend, setCustomPinterestTrend] = useState<PinterestOfficialTrendItem | null>(null);
  const [pinterestLoading, setPinterestLoading] = useState(false);
  const [pinterestSearching, setPinterestSearching] = useState(false);
  const [launchingInspoTerm, setLaunchingInspoTerm] = useState<string | null>(null);

  // ── Trend Deep-Dive Drawer State ─────────────
  const [selectedTrendTerm, setSelectedTrendTerm] = useState<string | null>(null);
  const [deepDiveData, setDeepDiveData] = useState<TrendDeepDiveResponse | null>(null);
  const [deepDiveLoading, setDeepDiveLoading] = useState(false);
  const [copiedKeywords, setCopiedKeywords] = useState(false);
  const [importingPinId, setImportingPinId] = useState<string | null>(null);
  const [importedPinIds, setImportedPinIds] = useState<Set<string>>(new Set());

  // ── Commercial Products State ────────────────
  const [commercialTrends, setCommercialTrends] = useState<TrendDossier[]>([]);
  const [selectedCategory, setSelectedCategory] = useState('all');
  const [customCommercialTrend, setCustomCommercialTrend] = useState<TrendDossier | null>(null);
  const [commercialLoading, setCommercialLoading] = useState(false);
  const [commercialSearching, setCommercialSearching] = useState(false);
  const [launchingAsin, setLaunchingAsin] = useState<string | null>(null);

  // ── Shared State ─────────────────────────────
  const [searchQuery, setSearchQuery] = useState('');
  const [launchSuccess, setLaunchSuccess] = useState<{ msg: string; jobId: string } | null>(null);
  const [rescanSuccess, setRescanSuccess] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const spotlightRef = useRef<HTMLDivElement>(null);

  // ── Fetch Official Pinterest Trends ──────────
  const fetchPinterestTrends = async (preset: string = pinterestPreset, intent: string = pinterestIntent, forceRefresh: boolean = false) => {
    setPinterestLoading(true);
    setError(null);
    try {
      const data = await api.getOfficialPinterestTrends(preset, intent, forceRefresh);
      setPinterestTrends(data.trends || []);
      if (forceRefresh) {
        setRescanSuccess(`Official Pinterest Trends updated from trends.pinterest.com! Refreshed 52-week search momentum & 20-day viral index windows.`);
        setTimeout(() => setRescanSuccess(null), 6000);
      }
    } catch (err: any) {
      console.error('Failed to load official Pinterest trends:', err);
      setError(err.message || 'Failed to scrape official Pinterest trends');
    } finally {
      setPinterestLoading(false);
    }
  };

  // ── Fetch Commercial Trends ──────────────────
  const fetchCommercialTrends = async (cat: string = selectedCategory, forceRefresh: boolean = false) => {
    setCommercialLoading(true);
    setError(null);
    try {
      const data = await api.getTrends(cat, forceRefresh);
      setCommercialTrends(data.trends || []);
      if (forceRefresh) {
        setRescanSuccess(`Market scan refreshed! Updated commercial search demand & live product matches.`);
        setTimeout(() => setRescanSuccess(null), 5000);
      }
    } catch (err: any) {
      console.error('Failed to load commercial trends:', err);
      setError(err.message || 'Failed to load market trends');
    } finally {
      setCommercialLoading(false);
    }
  };

  // Initial load
  useEffect(() => {
    if (radarMode === 'pinterest') {
      fetchPinterestTrends(pinterestPreset, pinterestIntent);
    } else {
      fetchCommercialTrends(selectedCategory);
    }
  }, [radarMode, pinterestPreset, pinterestIntent, selectedCategory]);

  // ── Search Handler ───────────────────────────
  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    const cleanQ = searchQuery.trim();
    if (!cleanQ) return;

    setError(null);

    if (radarMode === 'pinterest') {
      setPinterestSearching(true);
      try {
        const item = await api.queryOfficialPinterestTrend(cleanQ, true);
        setCustomPinterestTrend(item);
        setRescanSuccess(`Pinterest Search Intelligence ready for "${cleanQ}"! Found 52-week search trajectory & 20-day indexing advice.`);
        setTimeout(() => setRescanSuccess(null), 6000);
        setTimeout(() => {
          spotlightRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }, 100);
      } catch (err: any) {
        console.error('Pinterest trend query failed:', err);
        setError(err.message || 'Pinterest trend deep-scan failed');
      } finally {
        setPinterestSearching(false);
      }
    } else {
      setCommercialSearching(true);
      try {
        const cat = selectedCategory !== 'all' ? selectedCategory : 'fashion';
        const dossier = await api.queryTrend(cleanQ, cat, true);
        setCustomCommercialTrend(dossier);
        setRescanSuccess(`Deep scan complete for "${cleanQ}"! Found ${dossier.matched_products?.length || 0} live matched products.`);
        setTimeout(() => setRescanSuccess(null), 6000);
        setTimeout(() => {
          spotlightRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }, 100);
      } catch (err: any) {
        console.error('Trend query failed:', err);
        setError(err.message || 'Custom trend deep-scan failed');
      } finally {
        setCommercialSearching(false);
      }
    }
  };

  // ── Open Trend Deep Dive Drawer ───────────────
  const openTrendDeepDive = async (term: string) => {
    const clean = term.trim();
    if (!clean) return;
    setSelectedTrendTerm(clean);
    setDeepDiveLoading(true);
    setDeepDiveData(null);
    try {
      const data = await api.getOfficialPinterestTrendDetail(clean, 'US', false);
      setDeepDiveData(data);
    } catch (err: any) {
      console.error('Failed to load trend deep dive:', err);
      setError(err.message || `Failed to load deep dive for "${clean}"`);
    } finally {
      setDeepDiveLoading(false);
    }
  };

  // ── Copy Keywords to Clipboard ───────────────
  const handleCopyKeywords = (keywords: string[]) => {
    const text = keywords.join(', ');
    navigator.clipboard.writeText(text);
    setCopiedKeywords(true);
    setTimeout(() => setCopiedKeywords(false), 2500);
  };

  // ── 1-Click Import Pin to Style Reference ────
  const handleImportPinReference = async (pin: PopularPinItem, trendTerm: string, category: string) => {
    setImportingPinId(pin.pin_id);
    try {
      const res = await api.importPinReference({
        image_url: pin.image_url,
        pin_title: pin.title || pin.visual_hook || trendTerm,
        trend_label: trendTerm,
        category: category || 'fashion',
        source_pin_url: pin.pin_url,
      });
      setImportedPinIds((prev) => new Set([...prev, pin.pin_id]));
      setLaunchSuccess({
        msg: `Imported "${(pin.title || trendTerm).slice(0, 40)}..." into Style Reference Library with Visual DNA extracted!`,
        jobId: res.reference_id,
      });
      setTimeout(() => setLaunchSuccess(null), 7000);
    } catch (err: any) {
      console.error('Import pin reference failed:', err);
      setError(err.message || 'Failed to import pin as style reference');
    } finally {
      setImportingPinId(null);
    }
  };

  // ── Launch Inspo Campaign (Viral Blog / Idea) ─
  const handleLaunchInspoCampaign = async (
    trend: PinterestOfficialTrendItem | { term: string; category?: string; recommended_board?: string; preview_images?: string[] },
    previewUrl?: string
  ) => {
    setLaunchingInspoTerm(trend.term);
    setError(null);
    try {
      const res = await api.launchInspoCampaign({
        term: trend.term,
        category: trend.category || 'beauty',
        board_name: trend.recommended_board || `${trend.term} Inspo & Aesthetic Ideas`,
        preview_image_url: previewUrl || (trend.preview_images?.[0]),
        visual_prompt_notes: `Aesthetic pin for trending Pinterest search "${trend.term}". Focus on aesthetic inspiration, high saveability, and visual storytelling.`,
      });

      setLaunchSuccess({
        msg: `Viral Inspo Pin draft created for "${trend.term}"! Pre-seeded for Pinterest's 20-day indexing runway.`,
        jobId: res.job_id,
      });

      if (setSelectedJobId) setSelectedJobId(res.job_id);
      if (setSelectedProductId) setSelectedProductId(res.product_id);

      setTimeout(() => setLaunchSuccess(null), 7000);
    } catch (err: any) {
      console.error('Launch inspo campaign failed:', err);
      setError(err.message || 'Failed to launch inspo pin draft');
    } finally {
      setLaunchingInspoTerm(null);
    }
  };

  // ── Launch Commercial Amazon Campaign ────────
  const handleLaunchCommercialCampaign = async (trend: TrendDossier, prod: TrendProduct) => {
    if (prod.demo_only) {
      setError(`"${prod.title.slice(0, 50)}" is a curated demo example, not a live Amazon listing.`);
      return;
    }
    setLaunchingAsin(prod.asin);
    setError(null);
    try {
      const res = await api.launchTrendCampaign({
        asin: prod.asin,
        title: prod.title,
        price: prod.price,
        category: trend.category,
        image_url: prod.image_url,
        trend_label: trend.title,
        scene_setting: trend.outfit_or_scene,
        board_name: trend.recommended_board,
        affiliate_url: prod.affiliate_url,
        ...(trend.keyword_pack ? { keyword_pack: trend.keyword_pack } : {}),
      });

      setLaunchSuccess({
        msg: `Campaign successfully launched for "${prod.title.slice(0, 45)}..."! Job draft ready in Creative Lab.`,
        jobId: res.job_id,
      });

      if (setSelectedJobId) setSelectedJobId(res.job_id);
      if (setSelectedProductId) setSelectedProductId(res.product_id);

      setTimeout(() => setLaunchSuccess(null), 7000);
    } catch (err: any) {
      console.error('Launch campaign failed:', err);
      setError(err.message || 'Failed to launch campaign');
    } finally {
      setLaunchingAsin(null);
    }
  };

  const formatPercentage = (val: number | undefined | null) => {
    if (val === undefined || val === null) return 'N/A';
    const sign = val > 0 ? '+' : '';
    return `${sign}${val.toLocaleString()}%`;
  };

  const getUrgencyColor = (urgency: string) => {
    switch (urgency) {
      case 'immediate':
        return { bg: 'rgba(239, 68, 68, 0.15)', border: 'rgba(239, 68, 68, 0.4)', text: '#f87171' };
      case 'high':
        return { bg: 'rgba(249, 115, 22, 0.15)', border: 'rgba(249, 115, 22, 0.4)', text: '#fb923c' };
      case 'medium':
        return { bg: 'rgba(16, 185, 129, 0.15)', border: 'rgba(16, 185, 129, 0.4)', text: '#34d399' };
      default:
        return { bg: 'rgba(59, 130, 246, 0.15)', border: 'rgba(59, 130, 246, 0.4)', text: '#60a5fa' };
    }
  };

  const isCurrentLoading = radarMode === 'pinterest' ? pinterestLoading : commercialLoading;
  const isCurrentSearching = radarMode === 'pinterest' ? pinterestSearching : commercialSearching;

  return (
    <div style={{
      maxWidth: '1440px',
      margin: '0 auto',
      padding: '24px',
      display: 'flex',
      flexDirection: 'column',
      gap: '24px',
    }}>
      {/* ── Header & Main Mode Selector ──────────── */}
      <div style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'flex-start',
        flexWrap: 'wrap',
        gap: '16px',
      }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <div style={{
              width: '44px',
              height: '44px',
              borderRadius: '12px',
              background: radarMode === 'pinterest'
                ? 'linear-gradient(135deg, #e60023, #a855f7)'
                : 'linear-gradient(135deg, #ec4899, #8b5cf6)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              boxShadow: radarMode === 'pinterest'
                ? '0 4px 18px rgba(230, 0, 35, 0.4)'
                : '0 4px 16px rgba(236, 72, 153, 0.35)',
              transition: 'all 0.3s ease',
            }}>
              {radarMode === 'pinterest' ? <Sparkles size={24} color="#fff" /> : <Compass size={24} color="#fff" />}
            </div>
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <h1 style={{ fontSize: '1.65rem', fontWeight: 800, letterSpacing: '-0.02em', margin: 0 }}>
                  Pinterest Trend Intelligence & Early Radar
                </h1>
                <span style={{
                  background: 'rgba(16, 185, 129, 0.15)',
                  border: '1px solid rgba(16, 185, 129, 0.4)',
                  color: '#34d399',
                  padding: '2px 8px',
                  borderRadius: '9999px',
                  fontSize: '0.72rem',
                  fontWeight: 700,
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '4px',
                }}>
                  <span style={{ width: '6px', height: '6px', borderRadius: '50%', background: '#34d399' }} />
                  20-Day Indexing Buffer
                </span>
              </div>
              <p style={{ fontSize: '0.84rem', color: 'var(--text-secondary)', margin: '4px 0 0 0', maxWidth: '850px' }}>
                {radarMode === 'pinterest'
                  ? 'Real-time search trajectories from trends.pinterest.com. Pins take 15–30 days to index on Pinterest, so you can publish inspo pins before peak search volume arrives.'
                  : 'Commercial product signals combining Google Shopping autocomplete with high-converting Amazon affiliate product matching.'}
              </p>
            </div>
          </div>
        </div>

        {/* Rescan Button */}
        <button
          onClick={() => {
            if (radarMode === 'pinterest') {
              fetchPinterestTrends(pinterestPreset, pinterestIntent, true);
            } else {
              fetchCommercialTrends(selectedCategory, true);
            }
          }}
          disabled={isCurrentLoading}
          className="btn btn-secondary"
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            padding: '10px 18px',
            fontSize: '0.84rem',
            fontWeight: 700,
          }}
        >
          <RefreshCw size={15} className={isCurrentLoading ? 'animate-spin' : ''} />
          <span>{isCurrentLoading ? 'Scraping Live...' : radarMode === 'pinterest' ? 'Rescan Pinterest Trends' : 'Rescan Market'}</span>
        </button>
      </div>

      {/* ── Mode Segment Selector ─────────────────── */}
      <div style={{
        display: 'flex',
        gap: '12px',
        borderBottom: '1px solid var(--border-subtle)',
        paddingBottom: '16px',
        flexWrap: 'wrap',
      }}>
        <button
          onClick={() => {
            setRadarMode('pinterest');
            setSearchQuery('');
          }}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            padding: '10px 18px',
            borderRadius: '12px',
            fontSize: '0.88rem',
            fontWeight: 700,
            cursor: 'pointer',
            transition: 'all 0.2s ease',
            border: radarMode === 'pinterest' ? '1px solid #e60023' : '1px solid var(--border-subtle)',
            background: radarMode === 'pinterest'
              ? 'linear-gradient(135deg, rgba(230, 0, 35, 0.2), rgba(168, 85, 247, 0.15))'
              : 'rgba(13, 17, 23, 0.6)',
            color: radarMode === 'pinterest' ? '#fff' : 'var(--text-secondary)',
          }}
        >
          <Flame size={16} color={radarMode === 'pinterest' ? '#ff4757' : 'var(--text-muted)'} />
          <span>Official Pinterest Trends (Live Scraper)</span>
          <span style={{
            background: radarMode === 'pinterest' ? '#e60023' : 'rgba(255, 255, 255, 0.1)',
            color: '#fff',
            fontSize: '0.68rem',
            padding: '1px 6px',
            borderRadius: '9999px',
            fontWeight: 800,
          }}>
            VIRAL INSPO
          </span>
        </button>

        <button
          onClick={() => {
            setRadarMode('commercial');
            setSearchQuery('');
          }}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            padding: '10px 18px',
            borderRadius: '12px',
            fontSize: '0.88rem',
            fontWeight: 700,
            cursor: 'pointer',
            transition: 'all 0.2s ease',
            border: radarMode === 'commercial' ? '1px solid #a855f7' : '1px solid var(--border-subtle)',
            background: radarMode === 'commercial'
              ? 'linear-gradient(135deg, rgba(168, 85, 247, 0.2), rgba(59, 130, 246, 0.15))'
              : 'rgba(13, 17, 23, 0.6)',
            color: radarMode === 'commercial' ? '#fff' : 'var(--text-secondary)',
          }}
        >
          <ShoppingBag size={16} color={radarMode === 'commercial' ? '#c084fc' : 'var(--text-muted)'} />
          <span>Commercial Products (Amazon Affiliate Matcher)</span>
        </button>
      </div>

      {/* ── Notifications / Alerts ───────────────── */}
      {rescanSuccess && (
        <div style={{
          background: 'rgba(59, 130, 246, 0.12)',
          border: '1px solid rgba(59, 130, 246, 0.4)',
          borderRadius: '12px',
          padding: '14px 18px',
          display: 'flex',
          alignItems: 'center',
          gap: '10px',
        }}>
          <CheckCircle2 size={18} color="#3b82f6" />
          <span style={{ fontSize: '0.86rem', color: '#60a5fa', fontWeight: 600 }}>
            {rescanSuccess}
          </span>
        </div>
      )}

      {launchSuccess && (
        <div style={{
          background: 'rgba(16, 185, 129, 0.12)',
          border: '1px solid rgba(16, 185, 129, 0.4)',
          borderRadius: '12px',
          padding: '14px 18px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: '12px',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <CheckCircle2 size={18} color="#10b981" />
            <span style={{ fontSize: '0.86rem', color: '#34d399', fontWeight: 600 }}>
              {launchSuccess.msg}
            </span>
          </div>
          {setActiveTab && (
            <button
              onClick={() => setActiveTab('lab')}
              className="btn btn-primary"
              style={{
                padding: '6px 14px',
                fontSize: '0.78rem',
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
              }}
            >
              <span>Go to Creative Lab</span>
              <ArrowRight size={14} />
            </button>
          )}
        </div>
      )}

      {error && (
        <div style={{
          background: 'rgba(239, 68, 68, 0.12)',
          border: '1px solid rgba(239, 68, 68, 0.4)',
          borderRadius: '12px',
          padding: '14px 18px',
          display: 'flex',
          alignItems: 'center',
          gap: '10px',
        }}>
          <AlertCircle size={18} color="#ef4444" />
          <span style={{ fontSize: '0.86rem', color: '#f87171' }}>{error}</span>
        </div>
      )}

      {/* ── Search Bar & Filter Controls ─────────── */}
      <div style={{
        background: 'rgba(22, 27, 34, 0.75)',
        backdropFilter: 'blur(12px)',
        border: '1px solid var(--border-subtle)',
        borderRadius: '16px',
        padding: '20px',
        display: 'flex',
        flexDirection: 'column',
        gap: '16px',
      }}>
        <form onSubmit={handleSearch} style={{ display: 'flex', gap: '10px' }}>
          <div style={{
            position: 'relative',
            flex: 1,
            display: 'flex',
            alignItems: 'center',
          }}>
            <Search size={18} color="var(--text-muted)" style={{ position: 'absolute', left: '14px' }} />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder={
                radarMode === 'pinterest'
                  ? "Search official Pinterest Trend (e.g. 'fall nail colors 2026', 'halloween nails', 'september nails ideas', 'usa football outfit')..."
                  : "Search custom commercial trend (e.g. 'coastal cowgirl spring', 'japandi coffee bar', 'oversized vintage jacket')..."
              }
              style={{
                width: '100%',
                padding: '12px 14px 12px 42px',
                background: 'rgba(13, 17, 23, 0.85)',
                border: '1px solid var(--border-subtle)',
                borderRadius: '10px',
                color: '#fff',
                fontSize: '0.88rem',
                outline: 'none',
              }}
            />
          </div>
          <button
            type="submit"
            disabled={isCurrentSearching || !searchQuery.trim()}
            className="btn btn-primary"
            style={{
              padding: '0 22px',
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              fontWeight: 700,
              fontSize: '0.84rem',
            }}
          >
            {isCurrentSearching ? (
              <>
                <Loader2 size={16} className="animate-spin" />
                <span>Scanning...</span>
              </>
            ) : (
              <>
                <Sparkles size={16} />
                <span>Deep Scan</span>
              </>
            )}
          </button>
        </form>

        {/* Filters according to mode */}
        {radarMode === 'pinterest' ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            {/* Presets */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', overflowX: 'auto', paddingBottom: '2px' }}>
              <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)', fontWeight: 800, textTransform: 'uppercase', marginRight: '4px' }}>
                Preset:
              </span>
              {PINTEREST_PRESETS.map((p) => {
                const Icon = p.icon;
                const isSelected = pinterestPreset === p.id;
                return (
                  <button
                    key={p.id}
                    onClick={() => {
                      setPinterestPreset(p.id);
                      setCustomPinterestTrend(null);
                    }}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '6px',
                      padding: '6px 14px',
                      borderRadius: '9999px',
                      fontSize: '0.78rem',
                      fontWeight: 600,
                      cursor: 'pointer',
                      border: isSelected ? '1px solid #e60023' : '1px solid var(--border-subtle)',
                      background: isSelected ? 'rgba(230, 0, 35, 0.18)' : 'rgba(13, 17, 23, 0.6)',
                      color: isSelected ? '#ff6b81' : 'var(--text-secondary)',
                      transition: 'all 0.15s ease',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    <Icon size={13} color={isSelected ? '#ff6b81' : 'var(--text-muted)'} />
                    <span>{p.label}</span>
                  </button>
                );
              })}
            </div>

            {/* Intent Filter */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', overflowX: 'auto' }}>
              <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)', fontWeight: 800, textTransform: 'uppercase', marginRight: '4px' }}>
                Intent:
              </span>
              {PINTEREST_INTENTS.map((intent) => {
                const isSelected = pinterestIntent === intent.id;
                return (
                  <button
                    key={intent.id}
                    onClick={() => {
                      setPinterestIntent(intent.id);
                      setCustomPinterestTrend(null);
                    }}
                    style={{
                      padding: '5px 12px',
                      borderRadius: '9999px',
                      fontSize: '0.76rem',
                      fontWeight: 600,
                      cursor: 'pointer',
                      border: isSelected ? '1px solid #a855f7' : '1px solid var(--border-subtle)',
                      background: isSelected ? 'rgba(168, 85, 247, 0.2)' : 'rgba(13, 17, 23, 0.6)',
                      color: isSelected ? '#d8b4fe' : 'var(--text-secondary)',
                      transition: 'all 0.15s ease',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {intent.label}
                  </button>
                );
              })}
            </div>
          </div>
        ) : (
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', overflowX: 'auto', paddingBottom: '4px' }}>
            {COMMERCIAL_CATEGORIES.map((cat) => (
              <button
                key={cat.id}
                onClick={() => {
                  setSelectedCategory(cat.id);
                  setCustomCommercialTrend(null);
                }}
                style={{
                  padding: '7px 14px',
                  borderRadius: '9999px',
                  fontSize: '0.78rem',
                  fontWeight: 600,
                  border: selectedCategory === cat.id
                    ? '1px solid #a855f7'
                    : '1px solid var(--border-subtle)',
                  background: selectedCategory === cat.id
                    ? 'rgba(168, 85, 247, 0.2)'
                    : 'rgba(13, 17, 23, 0.6)',
                  color: selectedCategory === cat.id ? '#c084fc' : 'var(--text-secondary)',
                  cursor: 'pointer',
                  transition: 'all 0.15s ease',
                  whiteSpace: 'nowrap',
                }}
              >
                {cat.label}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* ── Custom Trend Spotlight (if queried) ──── */}
      {radarMode === 'pinterest' && customPinterestTrend && (
        <div
          ref={spotlightRef}
          style={{
            background: 'linear-gradient(180deg, rgba(230, 0, 35, 0.15) 0%, rgba(22, 27, 34, 0.9) 100%)',
            border: '1px solid rgba(230, 0, 35, 0.4)',
            borderRadius: '16px',
            padding: '24px',
            display: 'flex',
            flexDirection: 'column',
            gap: '20px',
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '12px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <span style={{
                background: 'rgba(230, 0, 35, 0.3)',
                color: '#ff6b81',
                padding: '4px 10px',
                borderRadius: '6px',
                fontSize: '0.74rem',
                fontWeight: 800,
                letterSpacing: '0.04em',
              }}>
                CUSTOM PINTEREST SPOTLIGHT
              </span>
              <span style={{
                fontSize: '0.74rem',
                color: 'var(--text-muted)',
                textTransform: 'uppercase',
                fontWeight: 700,
              }}>
                {customPinterestTrend.category}
              </span>
            </div>

            {/* Growth Badges */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '4px',
                padding: '3px 10px',
                borderRadius: '9999px',
                fontSize: '0.76rem',
                fontWeight: 800,
                background: customPinterestTrend.mom_change > 0 ? 'rgba(239, 68, 68, 0.15)' : 'rgba(59, 130, 246, 0.15)',
                border: customPinterestTrend.mom_change > 0 ? '1px solid rgba(239, 68, 68, 0.4)' : '1px solid rgba(59, 130, 246, 0.4)',
                color: customPinterestTrend.mom_change > 0 ? '#f87171' : '#60a5fa',
              }}>
                <Flame size={12} />
                {formatPercentage(customPinterestTrend.mom_change)} MoM
              </span>
              <span style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '4px',
                padding: '3px 10px',
                borderRadius: '9999px',
                fontSize: '0.76rem',
                fontWeight: 800,
                background: 'rgba(16, 185, 129, 0.15)',
                border: '1px solid rgba(16, 185, 129, 0.4)',
                color: '#34d399',
              }}>
                <TrendingUp size={12} />
                {formatPercentage(customPinterestTrend.wow_change)} WoW
              </span>
            </div>
          </div>

          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '16px' }}>
            <div>
              <h2 style={{ fontSize: '1.5rem', fontWeight: 800, margin: '0 0 6px 0', color: '#fff' }}>
                {customPinterestTrend.term}
              </h2>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '0.82rem', color: '#38bdf8' }}>
                <FolderPlus size={14} />
                <span>Target Board: {customPinterestTrend.recommended_board}</span>
              </div>
            </div>

            {/* Sparkline & Volume */}
            <div style={{
              display: 'flex',
              alignItems: 'center',
              gap: '16px',
              background: 'rgba(13, 17, 23, 0.8)',
              padding: '12px 18px',
              borderRadius: '12px',
              border: '1px solid var(--border-subtle)',
            }}>
              <div>
                <div style={{ fontSize: '0.68rem', color: 'var(--text-muted)', fontWeight: 800, textTransform: 'uppercase' }}>
                  52-Week Trajectory
                </div>
                <div style={{ fontSize: '0.86rem', color: '#fff', fontWeight: 700, marginTop: '2px' }}>
                  Normalized Volume: {customPinterestTrend.search_count}/100
                </div>
              </div>
              <SparklineGraph data={customPinterestTrend.sparkline} color="#ff4757" width={180} height={52} />
            </div>
          </div>

          {/* 20-Day Indexing Window Runway Banner */}
          {customPinterestTrend.indexing_window && (
            <div style={{
              background: getUrgencyColor(customPinterestTrend.indexing_window.urgency).bg,
              border: `1px solid ${getUrgencyColor(customPinterestTrend.indexing_window.urgency).border}`,
              borderRadius: '12px',
              padding: '14px 18px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              flexWrap: 'wrap',
              gap: '12px',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <Clock size={18} color={getUrgencyColor(customPinterestTrend.indexing_window.urgency).text} />
                <div>
                  <div style={{ fontSize: '0.88rem', fontWeight: 800, color: getUrgencyColor(customPinterestTrend.indexing_window.urgency).text }}>
                    {customPinterestTrend.indexing_window.advice}
                  </div>
                  <div style={{ fontSize: '0.76rem', color: 'var(--text-secondary)', marginTop: '2px' }}>
                    Pinterest pins require 15–30 days to index in search results. Pinning right now guarantees maximum search visibility when this curve peaks.
                  </div>
                </div>
              </div>
              <span style={{
                background: 'rgba(0, 0, 0, 0.3)',
                padding: '4px 10px',
                borderRadius: '6px',
                fontSize: '0.72rem',
                fontWeight: 800,
                color: '#fff',
              }}>
                {customPinterestTrend.indexing_window.badge}
              </span>
            </div>
          )}

          {/* Pinterest Previews and Action */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '14px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              {customPinterestTrend.preview_images && customPinterestTrend.preview_images.slice(0, 4).map((img, i) => (
                <img
                  key={i}
                  src={img}
                  alt={customPinterestTrend.term}
                  style={{
                    width: '64px',
                    height: '64px',
                    objectFit: 'cover',
                    borderRadius: '8px',
                    border: '1px solid var(--border-subtle)',
                  }}
                />
              ))}
              <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>
                {customPinterestTrend.monetization_angle}
              </div>
            </div>

            <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
              <button
                onClick={() => openTrendDeepDive(customPinterestTrend.term)}
                className="btn btn-secondary"
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '6px',
                  fontSize: '0.8rem',
                  padding: '8px 14px',
                  borderColor: 'rgba(230, 0, 35, 0.45)',
                  color: '#ff6b81',
                  background: 'rgba(230, 0, 35, 0.1)',
                }}
              >
                <Layers size={14} />
                <span>Deep Dive & Popular Pins</span>
              </button>

              <a
                href={`https://trends.pinterest.com/?terms=${encodeURIComponent(customPinterestTrend.term)}`}
                target="_blank"
                rel="noreferrer"
                className="btn btn-secondary"
                style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.8rem', padding: '8px 14px' }}
              >
                <ExternalLink size={13} />
                <span>View on Pinterest</span>
              </a>

              <button
                onClick={() => handleLaunchInspoCampaign(customPinterestTrend)}
                disabled={launchingInspoTerm === customPinterestTrend.term}
                className="btn btn-primary"
                style={{
                  padding: '8px 16px',
                  fontSize: '0.8rem',
                  fontWeight: 700,
                  display: 'flex',
                  alignItems: 'center',
                  gap: '6px',
                  background: 'linear-gradient(135deg, #e60023, #a855f7)',
                }}
              >
                {launchingInspoTerm === customPinterestTrend.term ? (
                  <>
                    <Loader2 size={14} className="animate-spin" />
                    <span>Preparing Inspo Draft...</span>
                  </>
                ) : (
                  <>
                    <Sparkles size={14} />
                    <span>1-Click Launch Inspo Pin</span>
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Official Pinterest Trends Feed ───────── */}
      {radarMode === 'pinterest' && (
        <>
          {pinterestLoading ? (
            <div style={{
              padding: '60px 0',
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '16px',
            }}>
              <Loader2 size={34} color="#e60023" className="animate-spin" />
              <span style={{ fontSize: '0.92rem', color: 'var(--text-secondary)' }}>
                Scraping live Pinterest Trends search graphs & calculating 20-day viral index windows...
              </span>
            </div>
          ) : pinterestTrends.length === 0 ? (
            <div style={{
              padding: '60px 0',
              textAlign: 'center',
              background: 'rgba(22, 27, 34, 0.4)',
              borderRadius: '16px',
              border: '1px dashed var(--border-subtle)',
            }}>
              <Compass size={40} color="var(--text-muted)" style={{ margin: '0 auto 12px auto' }} />
              <h3 style={{ fontSize: '1.1rem', fontWeight: 700, margin: '0 0 6px 0' }}>No trends found in this preset</h3>
              <p style={{ fontSize: '0.84rem', color: 'var(--text-secondary)', maxWidth: '400px', margin: '0 auto 16px auto' }}>
                Click "Rescan Pinterest Trends" or query a custom search term above.
              </p>
              <button
                onClick={() => fetchPinterestTrends(pinterestPreset, pinterestIntent, true)}
                className="btn btn-primary"
                style={{ padding: '8px 18px', fontSize: '0.82rem' }}
              >
                Rescan Signals
              </button>
            </div>
          ) : (
            <div style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fill, minmax(440px, 1fr))',
              gap: '20px',
            }}>
              {pinterestTrends.map((trend) => {
                const urgencyStyle = getUrgencyColor(trend.indexing_window?.urgency || 'normal');
                return (
                  <div
                    key={trend.term}
                    style={{
                      background: 'rgba(22, 27, 34, 0.85)',
                      backdropFilter: 'blur(12px)',
                      border: '1px solid var(--border-subtle)',
                      borderRadius: '16px',
                      padding: '20px',
                      display: 'flex',
                      flexDirection: 'column',
                      justifyContent: 'space-between',
                      gap: '16px',
                      transition: 'transform 0.15s ease, border-color 0.15s ease',
                    }}
                  >
                    {/* Top Row: Category + Intent + Growth Badges */}
                    <div>
                      <div style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                        marginBottom: '10px',
                      }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                          <span style={{
                            fontSize: '0.7rem',
                            color: '#ff6b81',
                            background: 'rgba(230, 0, 35, 0.15)',
                            padding: '2px 8px',
                            borderRadius: '6px',
                            fontWeight: 800,
                            letterSpacing: '0.04em',
                            textTransform: 'uppercase',
                          }}>
                            {trend.category}
                          </span>
                          <span style={{
                            fontSize: '0.7rem',
                            color: trend.intent === 'viral_blog' ? '#c084fc' : '#60a5fa',
                            background: trend.intent === 'viral_blog' ? 'rgba(168, 85, 247, 0.15)' : 'rgba(59, 130, 246, 0.15)',
                            padding: '2px 8px',
                            borderRadius: '6px',
                            fontWeight: 700,
                          }}>
                            {trend.intent === 'viral_blog' ? '💅 Viral Inspo' : '🛍️ Product'}
                          </span>
                        </div>

                        {/* MoM & WoW Badges */}
                        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                          <span style={{
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: '3px',
                            padding: '3px 8px',
                            borderRadius: '9999px',
                            fontSize: '0.72rem',
                            fontWeight: 800,
                            background: trend.mom_change > 0 ? 'rgba(239, 68, 68, 0.15)' : 'rgba(59, 130, 246, 0.15)',
                            border: trend.mom_change > 0 ? '1px solid rgba(239, 68, 68, 0.4)' : '1px solid rgba(59, 130, 246, 0.4)',
                            color: trend.mom_change > 0 ? '#f87171' : '#60a5fa',
                          }}>
                            <Flame size={11} />
                            {formatPercentage(trend.mom_change)} MoM
                          </span>
                          <span style={{
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: '3px',
                            padding: '3px 8px',
                            borderRadius: '9999px',
                            fontSize: '0.72rem',
                            fontWeight: 800,
                            background: 'rgba(16, 185, 129, 0.15)',
                            border: '1px solid rgba(16, 185, 129, 0.4)',
                            color: '#34d399',
                          }}>
                            {formatPercentage(trend.wow_change)} WoW
                          </span>
                        </div>
                      </div>

                      {/* Title & Sparkline */}
                      <div style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'flex-start',
                        gap: '12px',
                        marginBottom: '12px',
                      }}>
                        <div style={{ flex: 1 }}>
                          <h3
                            onClick={() => openTrendDeepDive(trend.term)}
                            title="Click to open full trend deep-dive & popular pins"
                            style={{
                              fontSize: '1.25rem',
                              fontWeight: 800,
                              margin: '0 0 6px 0',
                              color: '#fff',
                              lineHeight: 1.3,
                              cursor: 'pointer',
                              transition: 'color 0.15s ease',
                            }}
                            onMouseEnter={(e) => { e.currentTarget.style.color = '#ff6b81'; }}
                            onMouseLeave={(e) => { e.currentTarget.style.color = '#fff'; }}
                          >
                            {trend.term}
                          </h3>
                          <div style={{
                            display: 'flex',
                            alignItems: 'center',
                            gap: '6px',
                            fontSize: '0.76rem',
                            color: '#38bdf8',
                            fontWeight: 600,
                          }}>
                            <FolderPlus size={13} />
                            <span>{trend.recommended_board}</span>
                          </div>
                        </div>

                        {/* Sparkline Graph */}
                        <div style={{
                          background: 'rgba(13, 17, 23, 0.8)',
                          padding: '8px 12px',
                          borderRadius: '10px',
                          border: '1px solid var(--border-subtle)',
                          display: 'flex',
                          flexDirection: 'column',
                          alignItems: 'flex-end',
                        }}>
                          <SparklineGraph
                            data={trend.sparkline}
                            color={trend.mom_change > 100 ? '#ef4444' : '#a855f7'}
                            width={130}
                            height={40}
                          />
                          <span style={{ fontSize: '0.66rem', color: 'var(--text-muted)', marginTop: '2px', fontWeight: 600 }}>
                            Vol: {trend.search_count}/100
                          </span>
                        </div>
                      </div>

                      {/* 20-Day Indexing Buffer Recommendation */}
                      {trend.indexing_window && (
                        <div style={{
                          background: urgencyStyle.bg,
                          border: `1px solid ${urgencyStyle.border}`,
                          borderRadius: '10px',
                          padding: '10px 14px',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'space-between',
                          gap: '10px',
                          marginBottom: '12px',
                        }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                            <Clock size={15} color={urgencyStyle.text} />
                            <span style={{ fontSize: '0.78rem', fontWeight: 800, color: urgencyStyle.text }}>
                              {trend.indexing_window.advice}
                            </span>
                          </div>
                          <span style={{
                            fontSize: '0.68rem',
                            fontWeight: 700,
                            color: 'var(--text-muted)',
                            background: 'rgba(0, 0, 0, 0.25)',
                            padding: '2px 6px',
                            borderRadius: '4px',
                          }}>
                            {trend.indexing_window.badge}
                          </span>
                        </div>
                      )}

                      {/* Preview Pins from Pinterest */}
                      {trend.preview_images && trend.preview_images.length > 0 && (
                        <div style={{
                          display: 'flex',
                          alignItems: 'center',
                          gap: '8px',
                          marginBottom: '12px',
                          overflowX: 'auto',
                          paddingBottom: '4px',
                        }}>
                          {trend.preview_images.slice(0, 4).map((img, idx) => (
                            <img
                              key={idx}
                              src={img}
                              alt={trend.term}
                              style={{
                                width: '56px',
                                height: '56px',
                                objectFit: 'cover',
                                borderRadius: '8px',
                                border: '1px solid var(--border-subtle)',
                                flexShrink: 0,
                              }}
                            />
                          ))}
                          <div style={{ fontSize: '0.74rem', color: 'var(--text-muted)', paddingLeft: '4px' }}>
                            {trend.monetization_angle}
                          </div>
                        </div>
                      )}
                    </div>

                    {/* Card Actions */}
                    <div style={{
                      borderTop: '1px solid var(--border-subtle)',
                      paddingTop: '14px',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      gap: '10px',
                    }}>
                      <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            openTrendDeepDive(trend.term);
                          }}
                          className="btn btn-secondary"
                          style={{
                            padding: '7px 11px',
                            fontSize: '0.74rem',
                            display: 'flex',
                            alignItems: 'center',
                            gap: '5px',
                            borderColor: 'rgba(230, 0, 35, 0.45)',
                            color: '#ff6b81',
                            background: 'rgba(230, 0, 35, 0.08)',
                          }}
                          title="Explore 52-week trajectory, popular pins, and related search queries"
                        >
                          <Layers size={13} />
                          <span>Deep Dive & Pins</span>
                        </button>

                        <a
                          href={`https://trends.pinterest.com/?terms=${encodeURIComponent(trend.term)}`}
                          target="_blank"
                          rel="noreferrer"
                          title="View on trends.pinterest.com"
                          className="btn btn-secondary"
                          style={{
                            padding: '7px 10px',
                            fontSize: '0.74rem',
                            display: 'flex',
                            alignItems: 'center',
                            gap: '4px',
                          }}
                        >
                          <ExternalLink size={13} />
                          <span>Pinterest</span>
                        </a>

                        <a
                          href={`https://www.amazon.com/s?k=${encodeURIComponent(trend.term)}&tag=pinlookbooks-20`}
                          target="_blank"
                          rel="noreferrer"
                          title="Match Amazon Products"
                          className="btn btn-secondary"
                          style={{
                            padding: '7px 10px',
                            fontSize: '0.74rem',
                            display: 'flex',
                            alignItems: 'center',
                            gap: '4px',
                          }}
                        >
                          <ShoppingBag size={13} />
                          <span>Amazon</span>
                        </a>
                      </div>

                      <button
                        onClick={() => handleLaunchInspoCampaign(trend)}
                        disabled={launchingInspoTerm === trend.term}
                        className="btn btn-primary"
                        style={{
                          padding: '7px 14px',
                          fontSize: '0.76rem',
                          fontWeight: 700,
                          display: 'flex',
                          alignItems: 'center',
                          gap: '6px',
                          background: 'linear-gradient(135deg, #e60023, #a855f7)',
                        }}
                      >
                        {launchingInspoTerm === trend.term ? (
                          <>
                            <Loader2 size={13} className="animate-spin" />
                            <span>Creating Draft...</span>
                          </>
                        ) : (
                          <>
                            <Sparkles size={13} />
                            <span>1-Click Launch Inspo</span>
                          </>
                        )}
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </>
      )}

      {/* ── Commercial Mode Feed (Google + Amazon) ── */}
      {radarMode === 'commercial' && (
        <>
          {commercialLoading ? (
            <div style={{
              padding: '60px 0',
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '16px',
            }}>
              <Loader2 size={32} color="#a855f7" className="animate-spin" />
              <span style={{ fontSize: '0.9rem', color: 'var(--text-secondary)' }}>
                Analyzing commercial search intent and matching Amazon products...
              </span>
            </div>
          ) : commercialTrends.length === 0 ? (
            <div style={{
              padding: '60px 0',
              textAlign: 'center',
              background: 'rgba(22, 27, 34, 0.4)',
              borderRadius: '16px',
              border: '1px dashed var(--border-subtle)',
            }}>
              <Compass size={40} color="var(--text-muted)" style={{ margin: '0 auto 12px auto' }} />
              <h3 style={{ fontSize: '1.1rem', fontWeight: 700, margin: '0 0 6px 0' }}>No commercial trends found</h3>
              <p style={{ fontSize: '0.84rem', color: 'var(--text-secondary)', maxWidth: '400px', margin: '0 auto 16px auto' }}>
                Click "Rescan Market" to query live Google Shopping signals.
              </p>
              <button
                onClick={() => fetchCommercialTrends(selectedCategory, true)}
                className="btn btn-primary"
                style={{ padding: '8px 18px', fontSize: '0.82rem' }}
              >
                Rescan Signals
              </button>
            </div>
          ) : (
            <div style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fill, minmax(420px, 1fr))',
              gap: '20px',
            }}>
              {commercialTrends.map((trend) => (
                <div
                  key={trend.id}
                  style={{
                    background: 'rgba(22, 27, 34, 0.85)',
                    backdropFilter: 'blur(12px)',
                    border: '1px solid var(--border-subtle)',
                    borderRadius: '16px',
                    padding: '20px',
                    display: 'flex',
                    flexDirection: 'column',
                    justifyContent: 'space-between',
                    gap: '16px',
                  }}
                >
                  <div>
                    <div style={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                      marginBottom: '10px',
                    }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <span style={{
                          display: 'inline-flex',
                          alignItems: 'center',
                          gap: '4px',
                          padding: '3px 9px',
                          borderRadius: '9999px',
                          fontSize: '0.72rem',
                          fontWeight: 800,
                          background: 'rgba(16, 185, 129, 0.15)',
                          border: '1px solid rgba(16, 185, 129, 0.4)',
                          color: '#34d399',
                        }}>
                          <TrendingUp size={12} />
                          {trend.heat_badge || 'RISING DEMAND'}
                        </span>
                        <span style={{
                          fontSize: '0.7rem',
                          color: 'var(--text-muted)',
                          textTransform: 'uppercase',
                          fontWeight: 700,
                        }}>
                          {trend.category}
                        </span>
                      </div>

                      <div style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '4px',
                        background: 'rgba(234, 179, 8, 0.12)',
                        border: '1px solid rgba(234, 179, 8, 0.3)',
                        padding: '3px 8px',
                        borderRadius: '9999px',
                        fontSize: '0.72rem',
                        fontWeight: 800,
                        color: '#facc15',
                      }}>
                        <Star size={11} color="#facc15" fill="#facc15" />
                        <span>{trend.opportunity_score} Score</span>
                      </div>
                    </div>

                    <h3 style={{
                      fontSize: '1.2rem',
                      fontWeight: 800,
                      margin: '0 0 10px 0',
                      color: '#fff',
                      lineHeight: 1.3,
                    }}>
                      {trend.title}
                    </h3>

                    <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                      <div style={{
                        background: 'rgba(13, 17, 23, 0.6)',
                        padding: '10px 12px',
                        borderRadius: '8px',
                        border: '1px solid rgba(255, 255, 255, 0.04)',
                      }}>
                        <span style={{ fontSize: '0.68rem', color: '#a855f7', fontWeight: 800, display: 'block', marginBottom: '2px' }}>
                          AESTHETIC VIBE
                        </span>
                        <span style={{ fontSize: '0.78rem', color: '#cbd5e1', lineHeight: 1.35 }}>
                          {trend.aesthetic_vibe}
                        </span>
                      </div>

                      <div style={{
                        background: 'rgba(13, 17, 23, 0.6)',
                        padding: '10px 12px',
                        borderRadius: '8px',
                        border: '1px solid rgba(255, 255, 255, 0.04)',
                      }}>
                        <span style={{ fontSize: '0.68rem', color: '#38bdf8', fontWeight: 800, display: 'block', marginBottom: '2px' }}>
                          SCENE / OUTFIT FORMULA
                        </span>
                        <span style={{ fontSize: '0.78rem', color: '#cbd5e1', lineHeight: 1.35 }}>
                          {trend.outfit_or_scene}
                        </span>
                      </div>
                    </div>

                    <div style={{
                      marginTop: '12px',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '6px',
                      fontSize: '0.74rem',
                      color: '#34d399',
                      fontWeight: 600,
                    }}>
                      <FolderPlus size={13} />
                      <span>{trend.recommended_board}</span>
                    </div>
                  </div>

                  {/* Matched Product */}
                  <div style={{
                    borderTop: '1px solid var(--border-subtle)',
                    paddingTop: '14px',
                  }}>
                    {trend.matched_products && trend.matched_products.length > 0 && (
                      <div style={{
                        background: 'rgba(13, 17, 23, 0.9)',
                        border: '1px solid rgba(255, 255, 255, 0.06)',
                        borderRadius: '10px',
                        padding: '10px',
                        display: 'flex',
                        flexDirection: 'column',
                        gap: '10px',
                      }}>
                        {trend.matched_products.slice(0, 1).map((prod) => (
                          <div key={prod.asin}>
                            <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
                              <img
                                src={prod.image_url}
                                alt={prod.title}
                                style={{
                                  width: '52px',
                                  height: '52px',
                                  objectFit: 'cover',
                                  borderRadius: '6px',
                                  border: '1px solid var(--border-subtle)',
                                  flexShrink: 0,
                                }}
                              />
                              <div style={{ flex: 1, minWidth: 0 }}>
                                <a
                                  href={prod.affiliate_url}
                                  target="_blank"
                                  rel="noreferrer"
                                  style={{
                                    fontSize: '0.76rem',
                                    fontWeight: 600,
                                    color: '#fff',
                                    textDecoration: 'none',
                                    display: '-webkit-box',
                                    WebkitLineClamp: 2,
                                    WebkitBoxOrient: 'vertical',
                                    overflow: 'hidden',
                                  }}
                                >
                                  {prod.title}
                                </a>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginTop: '4px' }}>
                                  <span style={{ fontSize: '0.82rem', fontWeight: 800, color: '#10b981' }}>
                                    ${typeof prod.price === 'number' ? prod.price.toFixed(2) : prod.price}
                                  </span>
                                </div>
                              </div>
                            </div>

                            <button
                              onClick={() => handleLaunchCommercialCampaign(trend, prod)}
                              disabled={launchingAsin === prod.asin || prod.demo_only}
                              className="btn btn-primary"
                              style={{
                                width: '100%',
                                marginTop: '10px',
                                padding: '8px',
                                fontSize: '0.76rem',
                                fontWeight: 700,
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'center',
                                gap: '6px',
                                opacity: prod.demo_only ? 0.55 : 1,
                              }}
                            >
                              {launchingAsin === prod.asin ? (
                                <>
                                  <Loader2 size={13} className="animate-spin" />
                                  <span>Launching Campaign...</span>
                                </>
                              ) : (
                                <>
                                  <Sparkles size={13} />
                                  <span>1-Click Launch Campaign</span>
                                </>
                              )}
                            </button>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </>
      )}
      {/* ── Trend Deep-Dive Slide-Over Drawer ─── */}
      <TrendDeepDiveDrawer
        isOpen={Boolean(selectedTrendTerm)}
        onClose={() => setSelectedTrendTerm(null)}
        term={selectedTrendTerm || ''}
        data={deepDiveData}
        loading={deepDiveLoading}
        onSelectKeyword={(kw) => openTrendDeepDive(kw)}
        onImportPinReference={handleImportPinReference}
        onLaunchInspo={(term, category, previewUrl) => {
          handleLaunchInspoCampaign({ term, category }, previewUrl);
        }}
        importingPinId={importingPinId}
        importedPinIds={importedPinIds}
        launchingInspoTerm={launchingInspoTerm}
        copiedKeywords={copiedKeywords}
        onCopyKeywords={handleCopyKeywords}
      />
    </div>
  );
};
