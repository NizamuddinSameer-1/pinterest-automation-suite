import React, { useState, useEffect } from 'react';
import { api, TrendDossier, TrendProduct } from '../api';
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
} from 'lucide-react';

interface TrendRadarProps {
  setActiveTab?: (tab: string) => void;
  setSelectedJobId?: (id: string) => void;
  setSelectedProductId?: (id: string) => void;
}

const CATEGORIES = [
  { id: 'all', label: 'All Signals' },
  { id: 'fashion', label: '👗 Fashion & Outfits' },
  { id: 'home', label: '🏡 Home Decor' },
  { id: 'kitchen', label: '☕ Kitchen & Lifestyle' },
  { id: 'tech', label: '💻 Tech & Desk' },
  { id: 'seasonal', label: '🌸 Seasonal 2026' },
];

export const TrendRadar: React.FC<TrendRadarProps> = ({
  setActiveTab,
  setSelectedJobId,
  setSelectedProductId,
}) => {
  const [trends, setTrends] = useState<TrendDossier[]>([]);
  const [selectedCategory, setSelectedCategory] = useState('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const [searching, setSearching] = useState(false);
  const [customTrend, setCustomTrend] = useState<TrendDossier | null>(null);
  const [launchingAsin, setLaunchingAsin] = useState<string | null>(null);
  const [launchSuccess, setLaunchSuccess] = useState<{ msg: string; jobId: string } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const fetchTrends = async (cat: string = selectedCategory) => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.getTrends(cat);
      setTrends(data.trends || []);
    } catch (err: any) {
      console.error('Failed to load trends:', err);
      setError(err.message || 'Failed to load market trends');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchTrends(selectedCategory);
  }, [selectedCategory]);

  const handleCustomSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!searchQuery.trim()) return;

    setSearching(true);
    setError(null);
    try {
      const dossier = await api.queryTrend(searchQuery.trim());
      setCustomTrend(dossier);
    } catch (err: any) {
      console.error('Trend query failed:', err);
      setError(err.message || 'Custom trend deep-scan failed');
    } finally {
      setSearching(false);
    }
  };

  const handleLaunchCampaign = async (trend: TrendDossier, prod: TrendProduct) => {
    if (prod.demo_only) {
      setError(`"${prod.title.slice(0, 50)}" is a curated demo example, not a live Amazon listing. Launch is disabled until live PA-API results arrive.`);
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

      if (setSelectedJobId) {
        setSelectedJobId(res.job_id);
      }
      if (setSelectedProductId) {
        setSelectedProductId(res.product_id);
      }

      setTimeout(() => {
        setLaunchSuccess(null);
      }, 7000);
    } catch (err: any) {
      console.error('Launch campaign failed:', err);
      setError(err.message || 'Failed to launch campaign');
    } finally {
      setLaunchingAsin(null);
    }
  };

  const getTrendBadge = (heat_level: string, heat_badge: string) => {
    if (heat_level === 'breakout') {
      return (
        <span style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: '4px',
          padding: '3px 9px',
          borderRadius: '9999px',
          fontSize: '0.72rem',
          fontWeight: 800,
          background: 'rgba(239, 68, 68, 0.15)',
          border: '1px solid rgba(239, 68, 68, 0.4)',
          color: '#f87171',
        }}>
          <Flame size={12} color="#f87171" />
          {heat_badge || 'BREAKOUT'}
        </span>
      );
    }
    if (heat_level === 'rising') {
      return (
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
          <TrendingUp size={12} color="#34d399" />
          {heat_badge || 'RISING DEMAND'}
        </span>
      );
    }
    return (
      <span style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: '4px',
        padding: '3px 9px',
        borderRadius: '9999px',
        fontSize: '0.72rem',
        fontWeight: 800,
        background: 'rgba(59, 130, 246, 0.15)',
        border: '1px solid rgba(59, 130, 246, 0.4)',
        color: '#60a5fa',
      }}>
        <Zap size={12} color="#60a5fa" />
        {heat_badge || 'EVERGREEN'}
      </span>
    );
  };

  return (
    <div style={{
      maxWidth: '1440px',
      margin: '0 auto',
      padding: '24px',
      display: 'flex',
      flexDirection: 'column',
      gap: '24px',
    }}>
      {/* ── Header & Title ────────────────────────── */}
      <div style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'flex-start',
        flexWrap: 'wrap',
        gap: '16px',
      }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <div style={{
              width: '40px',
              height: '40px',
              borderRadius: '12px',
              background: 'linear-gradient(135deg, #ec4899, #8b5cf6)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              boxShadow: '0 4px 16px rgba(236, 72, 153, 0.35)',
            }}>
              <Compass size={22} color="#fff" />
            </div>
            <div>
              <h1 style={{ fontSize: '1.6rem', fontWeight: 800, letterSpacing: '-0.02em', margin: 0 }}>
                Real-Time Trend Radar
              </h1>
              <p style={{ fontSize: '0.84rem', color: 'var(--text-secondary)', margin: '2px 0 0 0' }}>
                Live commercial search demand from Google Shopping Autocomplete + Pinterest aesthetic taxonomy matched with high-converting Amazon affiliate products.
              </p>
            </div>
          </div>
        </div>

        {/* Rescan Button */}
        <button
          onClick={() => fetchTrends(selectedCategory)}
          disabled={loading}
          className="btn btn-secondary"
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            padding: '9px 16px',
            fontSize: '0.82rem',
            fontWeight: 700,
          }}
        >
          <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
          <span>{loading ? 'Scanning Market...' : 'Rescan Market'}</span>
        </button>
      </div>

      {/* ── Notifications / Alerts ───────────────── */}
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

      {/* ── Search Bar & Category Filter ─────────── */}
      <div style={{
        background: 'rgba(22, 27, 34, 0.7)',
        backdropFilter: 'blur(12px)',
        border: '1px solid var(--border-subtle)',
        borderRadius: '16px',
        padding: '18px 20px',
        display: 'flex',
        flexDirection: 'column',
        gap: '16px',
      }}>
        <form onSubmit={handleCustomSearch} style={{ display: 'flex', gap: '10px' }}>
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
              placeholder="Search custom trend, aesthetic, or product (e.g. 'coastal cowgirl spring', 'japandi coffee bar', 'vintage oversized leather jacket')..."
              style={{
                width: '100%',
                padding: '12px 14px 12px 42px',
                background: 'rgba(13, 17, 23, 0.8)',
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
            disabled={searching || !searchQuery.trim()}
            className="btn btn-primary"
            style={{
              padding: '0 20px',
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              fontWeight: 700,
              fontSize: '0.84rem',
            }}
          >
            {searching ? (
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

        {/* Category Pills */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', overflowX: 'auto', paddingBottom: '4px' }}>
          {CATEGORIES.map((cat) => (
            <button
              key={cat.id}
              onClick={() => {
                setSelectedCategory(cat.id);
                setCustomTrend(null);
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
      </div>

      {/* ── Custom Trend Result (if queried) ───── */}
      {customTrend && (
        <div style={{
          background: 'linear-gradient(180deg, rgba(168, 85, 247, 0.12) 0%, rgba(22, 27, 34, 0.8) 100%)',
          border: '1px solid rgba(168, 85, 247, 0.4)',
          borderRadius: '16px',
          padding: '24px',
          display: 'flex',
          flexDirection: 'column',
          gap: '20px',
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '12px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <span style={{
                background: 'rgba(168, 85, 247, 0.25)',
                color: '#d8b4fe',
                padding: '4px 10px',
                borderRadius: '6px',
                fontSize: '0.72rem',
                fontWeight: 800,
                letterSpacing: '0.04em',
              }}>
                CUSTOM SCAN SPOTLIGHT
              </span>
              {getTrendBadge(customTrend.heat_level, customTrend.heat_badge)}
            </div>
            <div style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              background: 'rgba(234, 179, 8, 0.15)',
              border: '1px solid rgba(234, 179, 8, 0.4)',
              padding: '4px 12px',
              borderRadius: '9999px',
              fontSize: '0.78rem',
              fontWeight: 800,
              color: '#facc15',
            }}>
              <Star size={13} color="#facc15" fill="#facc15" />
              <span>Opportunity Score: {customTrend.opportunity_score}/100</span>
            </div>
          </div>

          <div>
            <h2 style={{ fontSize: '1.4rem', fontWeight: 800, margin: '0 0 8px 0', color: '#fff' }}>
              {customTrend.title}
            </h2>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '14px' }}>
              <div style={{
                background: 'rgba(13, 17, 23, 0.7)',
                padding: '12px 16px',
                borderRadius: '10px',
                border: '1px solid var(--border-subtle)',
              }}>
                <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', fontWeight: 700, marginBottom: '4px' }}>
                  AESTHETIC VIBE (DNA)
                </div>
                <div style={{ fontSize: '0.82rem', color: '#e2e8f0', lineHeight: 1.4 }}>
                  {customTrend.aesthetic_vibe}
                </div>
              </div>

              <div style={{
                background: 'rgba(13, 17, 23, 0.7)',
                padding: '12px 16px',
                borderRadius: '10px',
                border: '1px solid var(--border-subtle)',
              }}>
                <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', fontWeight: 700, marginBottom: '4px' }}>
                  SCENE / OUTFIT FORMULA
                </div>
                <div style={{ fontSize: '0.82rem', color: '#e2e8f0', lineHeight: 1.4 }}>
                  {customTrend.outfit_or_scene}
                </div>
              </div>

              <div style={{
                background: 'rgba(13, 17, 23, 0.7)',
                padding: '12px 16px',
                borderRadius: '10px',
                border: '1px solid var(--border-subtle)',
              }}>
                <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', fontWeight: 700, marginBottom: '4px' }}>
                  TARGET PINTEREST BOARD
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.82rem', color: '#38bdf8', fontWeight: 600 }}>
                  <FolderPlus size={14} />
                  <span>{customTrend.recommended_board}</span>
                </div>
              </div>
            </div>
          </div>

          {customTrend.score_breakdown && (
            <div style={{ display: 'flex', gap: '8px', fontSize: '0.72rem', color: 'var(--text-muted)' }}>
              <span>Demand {customTrend.score_breakdown.demand}</span>
              <span>Money {customTrend.score_breakdown.money}</span>
              <span>Win {customTrend.score_breakdown.winnability}</span>
            </div>
          )}

          {(customTrend.sources || []).length > 0 && (
            <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
              {(customTrend.sources || []).map((s, idx: number) => (
                <span key={idx} title={s.source + ': ' + s.status} style={{ display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
                  <span style={{ width: '8px', height: '8px', borderRadius: '9999px', background: s.status === 'fresh' ? '#34d399' : '#f59e0b', display: 'inline-block' }} />
                  {s.status !== 'fresh' && (
                    <span style={{ fontSize: '0.68rem', color: '#f59e0b', fontWeight: 600 }}>stale</span>
                  )}
                </span>
              ))}
            </div>
          )}

          {customTrend.keyword_pack?.long_tails && (
            <div>
              <div style={{ fontSize: '0.74rem', color: 'var(--text-muted)', fontWeight: 700, marginBottom: '8px' }}>
                KEYWORD PACK — {customTrend.keyword_pack.primary}
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                {(customTrend.keyword_pack.long_tails as string[]).slice(0, 4).map((q: string, idx: number) => (
                  <span
                    key={idx}
                    style={{
                      background: 'rgba(255, 255, 255, 0.05)',
                      border: '1px solid rgba(255, 255, 255, 0.1)',
                      borderRadius: '6px',
                      padding: '4px 10px',
                      fontSize: '0.74rem',
                      color: '#94a3b8',
                    }}
                  >
                    "{q}"
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Search Queries */}
          <div>
            <div style={{ fontSize: '0.74rem', color: 'var(--text-muted)', fontWeight: 700, marginBottom: '8px' }}>
              HIGH-INTENT COMMERCIAL SEARCH QUERIES
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
              {customTrend.related_queries.map((q, idx) => (
                <span
                  key={idx}
                  style={{
                    background: 'rgba(255, 255, 255, 0.05)',
                    border: '1px solid rgba(255, 255, 255, 0.1)',
                    borderRadius: '6px',
                    padding: '4px 10px',
                    fontSize: '0.74rem',
                    color: '#94a3b8',
                  }}
                >
                  "{q}"
                </span>
              ))}
            </div>
          </div>

          {/* Matched Amazon Products */}
          <div>
            <div style={{ fontSize: '0.74rem', color: 'var(--text-muted)', fontWeight: 700, marginBottom: '10px' }}>
              MATCHED HIGH-CONVERTING AMAZON AFFILIATE PRODUCTS
            </div>
            <div style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))',
              gap: '14px',
            }}>
              {customTrend.matched_products.map((prod) => (
                <div
                  key={prod.asin}
                  style={{
                    background: 'rgba(13, 17, 23, 0.8)',
                    border: '1px solid var(--border-subtle)',
                    borderRadius: '12px',
                    padding: '14px',
                    display: 'flex',
                    flexDirection: 'column',
                    justifyContent: 'space-between',
                    gap: '12px',
                  }}
                >
                  <div style={{ display: 'flex', gap: '12px' }}>
                    <img
                      src={prod.image_url}
                      alt={prod.title}
                      style={{
                        width: '64px',
                        height: '64px',
                        objectFit: 'cover',
                        borderRadius: '8px',
                        border: '1px solid var(--border-subtle)',
                      }}
                    />
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <a
                        href={prod.affiliate_url}
                        target="_blank"
                        rel="noreferrer"
                        style={{
                          fontSize: '0.8rem',
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
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginTop: '6px' }}>
                        <span style={{ fontSize: '0.84rem', fontWeight: 800, color: '#10b981' }}>
                          ${typeof prod.price === 'number' ? prod.price.toFixed(2) : prod.price}
                        </span>
                        {prod.rating && (
                          <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '3px' }}>
                            <Star size={11} color="#facc15" fill="#facc15" />
                            {prod.rating}
                          </span>
                        )}
                      </div>
                    </div>
                  </div>

                  <button
                    onClick={() => handleLaunchCampaign(customTrend, prod)}
                    disabled={launchingAsin === prod.asin || prod.demo_only}
                    title={prod.demo_only ? 'Curated demo example — launch disabled until live Amazon results arrive' : undefined}
                    className="btn btn-primary"
                    style={{
                      width: '100%',
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
                        <span>Launching...</span>
                      </>
                    ) : prod.demo_only ? (
                      <>
                        <Sparkles size={13} />
                        <span>Demo Example — No Live Listing</span>
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
          </div>
        </div>
      )}

      {/* ── Main Trend Feed ──────────────────────── */}
      {loading ? (
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
            Analyzing commercial search intent and generating aesthetic dossiers...
          </span>
        </div>
      ) : trends.length === 0 ? (
        <div style={{
          padding: '60px 0',
          textAlign: 'center',
          background: 'rgba(22, 27, 34, 0.4)',
          borderRadius: '16px',
          border: '1px dashed var(--border-subtle)',
        }}>
          <Compass size={40} color="var(--text-muted)" style={{ margin: '0 auto 12px auto' }} />
          <h3 style={{ fontSize: '1.1rem', fontWeight: 700, margin: '0 0 6px 0' }}>No trends found in this view</h3>
          <p style={{ fontSize: '0.84rem', color: 'var(--text-secondary)', maxWidth: '400px', margin: '0 auto 16px auto' }}>
            Click "Rescan Market" to query live Google Shopping signals or enter a custom trend in the search box above.
          </p>
          <button
            onClick={() => fetchTrends(selectedCategory)}
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
          {trends.map((trend) => (
            <div
              key={trend.id}
              style={{
                background: 'rgba(22, 27, 34, 0.8)',
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
              {/* Card Header */}
              <div>
                <div style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  marginBottom: '10px',
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    {getTrendBadge(trend.heat_level, trend.heat_badge)}
                    <span style={{
                      fontSize: '0.7rem',
                      color: 'var(--text-muted)',
                      textTransform: 'uppercase',
                      fontWeight: 700,
                      letterSpacing: '0.04em',
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
                {trend.score_breakdown && (
                  <div style={{ display: 'flex', gap: '8px', marginTop: '8px', fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                    <span>Demand {trend.score_breakdown.demand}</span>
                    <span>Money {trend.score_breakdown.money}</span>
                    <span>Win {trend.score_breakdown.winnability}</span>
                  </div>
                )}

                <h3 style={{
                  fontSize: '1.2rem',
                  fontWeight: 800,
                  margin: '0 0 10px 0',
                  color: '#fff',
                  lineHeight: 1.3,
                }}>
                  {trend.title}
                </h3>

                {/* Vibe & Formula */}
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

                {/* Target Board & Tags */}
                <div style={{
                  marginTop: '12px',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  flexWrap: 'wrap',
                  gap: '8px',
                }}>
                  <div style={{
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

                  <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap' }}>
                    {trend.related_queries.slice(0, 2).map((q, idx) => (
                      <span
                        key={idx}
                        style={{
                          fontSize: '0.68rem',
                          color: 'var(--text-muted)',
                          background: 'rgba(255, 255, 255, 0.04)',
                          padding: '2px 6px',
                          borderRadius: '4px',
                        }}
                      >
                        {q}
                      </span>
                    ))}
                  </div>
                  {(trend.keyword_pack?.long_tails) && (
                    <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap', marginTop: '6px' }}>
                      {(trend.keyword_pack.long_tails as string[]).slice(0, 4).map((q: string, idx: number) => (
                        <span
                          key={idx}
                          style={{
                            fontSize: '0.68rem',
                            color: 'var(--text-muted)',
                            background: 'rgba(255, 255, 255, 0.04)',
                            padding: '2px 6px',
                            borderRadius: '4px',
                          }}
                        >
                          {q}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              </div>

              {/* Matched Amazon Products Section */}
              <div style={{
                borderTop: '1px solid var(--border-subtle)',
                paddingTop: '14px',
                display: 'flex',
                flexDirection: 'column',
                gap: '10px',
              }}>
                <div style={{
                  fontSize: '0.72rem',
                  fontWeight: 700,
                  color: 'var(--text-muted)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                }}>
                  <span>AFFILIATE PRODUCT MATCH</span>
                  {trend.matched_products?.[0]?.demo_only ? (
                    <span style={{ color: '#a78bfa' }}>Curated Example (offline)</span>
                  ) : (
                    <span style={{ color: '#f59e0b' }}>Amazon Prime Verified</span>
                  )}
                </div>
                {(trend.sources || []).length > 0 && (
                  <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
                    {(trend.sources || []).map((s, idx: number) => (
                      <span key={idx} title={s.source + ': ' + s.status} style={{ display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
                        <span style={{ width: '8px', height: '8px', borderRadius: '9999px', background: s.status === 'fresh' ? '#34d399' : '#f59e0b', display: 'inline-block' }} />
                        {s.status !== 'fresh' && (
                          <span style={{ fontSize: '0.68rem', color: '#f59e0b', fontWeight: 600 }}>stale</span>
                        )}
                      </span>
                    ))}
                  </div>
                )}

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
                              {prod.rating && (
                                <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '2px' }}>
                                  <Star size={10} color="#facc15" fill="#facc15" />
                                  {prod.rating}
                                </span>
                              )}
                            </div>
                          </div>
                        </div>

                        <button
                          onClick={() => handleLaunchCampaign(trend, prod)}
                          disabled={launchingAsin === prod.asin || prod.demo_only}
                          title={prod.demo_only ? 'Curated demo example — launch disabled until live Amazon results arrive' : undefined}
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
                          ) : prod.demo_only ? (
                            <>
                              <Sparkles size={13} />
                              <span>Demo Example — No Live Listing</span>
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
    </div>
  );
};
