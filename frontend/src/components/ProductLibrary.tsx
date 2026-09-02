import React, { useState, useEffect } from 'react';
import { api, AmazonItem, Product } from '../api';
import {
  Search,
  Sparkles,
  Link as LinkIcon,
  ExternalLink,
  Star,
  CheckCircle,
  Loader2,
  PackagePlus,
  TrendingUp,
  ShieldCheck,
  X,
  ArrowRight,
  Package,
  Layers,
  Trash2,
  Copy,
  Check,
  Sparkle,
} from 'lucide-react';

const QUICK_TRENDS = [
  'Floral Summer Midi Dress',
  'Oversized Vintage Leather Jacket',
  'Aesthetic Ghost Lamp Ambient',
  'Chunky Knit Cardigan Sweater',
  'Minimalist Acrylic Desk Organizer',
  'Puffer Tote Bag Y2K',
  'Square Neck Puff Sleeve Top',
  'Mushroom Glass Table Lamp',
];

interface Props {
  setActiveTab?: (tab: string) => void;
  setSelectedProductId?: (id: string) => void;
  onProductImported?: (productId: string) => void;
}

export const ProductLibrary: React.FC<Props> = ({ setActiveTab, setSelectedProductId, onProductImported }) => {
  const [activeTab, setActiveTabState] = useState<'search' | 'direct' | 'saved'>('search');
  const [query, setQuery] = useState('');
  const [directInput, setDirectInput] = useState('');
  const [items, setItems] = useState<AmazonItem[]>([]);
  const [savedProducts, setSavedProducts] = useState<Product[]>([]);
  const [savedFilter, setSavedFilter] = useState('');
  const [loading, setLoading] = useState(false);
  const [loadingSaved, setLoadingSaved] = useState(false);
  const [importingAsin, setImportingAsin] = useState<string | null>(null);
  const [importedAsins, setImportedAsins] = useState<Set<string>>(new Set());
  const [copiedLink, setCopiedLink] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  const showSuccess = (msg: string) => {
    setSuccessMsg(msg);
    setTimeout(() => setSuccessMsg(null), 3500);
  };

  const loadSavedProducts = async () => {
    setLoadingSaved(true);
    try {
      const data = await api.getProducts();
      setSavedProducts(data || []);
      // Mark ASINs as imported
      const asins = new Set<string>();
      (data || []).forEach((p) => {
        if (p.product_truth?.asin) asins.add(p.product_truth.asin);
      });
      setImportedAsins(asins);
    } catch (err: any) {
      console.error('Failed to load saved products', err);
    } finally {
      setLoadingSaved(false);
    }
  };

  useEffect(() => {
    loadSavedProducts();
  }, []);

  const handleSearch = async (searchQuery: string) => {
    const q = searchQuery.trim();
    if (!q) return;
    setError(null);
    setItems([]);
    setLoading(true);
    try {
      const res = await api.searchAmazon(q, 'All', 8);
      if (res.success && res.items && res.items.length > 0) {
        setItems(res.items);
      } else {
        setError('No products found for this keyword. Try another search phrase.');
      }
    } catch (err: any) {
      setError(err.message || 'Failed to search Amazon products');
    } finally {
      setLoading(false);
    }
  };

  const handleDirectImport = async () => {
    const input = directInput.trim();
    if (!input) return;
    setError(null);
    setLoading(true);
    try {
      const res = await api.ingestAmazon(input);
      if (res.success && res.product_id) {
        setImportedAsins((prev) => new Set(prev).add(res.asin));
        showSuccess(`"${res.name}" imported successfully! Added to your Saved Products.`);
        loadSavedProducts();
        if (onProductImported) onProductImported(res.product_id);
        setDirectInput('');
      }
    } catch (err: any) {
      setError(err.message || 'Failed to import product. Please check the ASIN or URL.');
    } finally {
      setLoading(false);
    }
  };

  const handleImportItem = async (item: AmazonItem) => {
    setError(null);
    setImportingAsin(item.asin);
    try {
      const res = await api.ingestAmazon(item.asin);
      if (res.success && res.product_id) {
        setImportedAsins((prev) => new Set(prev).add(item.asin));
        showSuccess(`"${res.name}" imported! Smart Link ready.`);
        loadSavedProducts();
        if (onProductImported) onProductImported(res.product_id);
      }
    } catch (err: any) {
      setError(err.message || `Failed to import ${item.asin}`);
    } finally {
      setImportingAsin(null);
    }
  };

  const handleDeleteProduct = async (id: string, name: string) => {
    if (!window.confirm(`Delete "${name}" from your product library?`)) return;
    try {
      await api.deleteProduct(id);
      showSuccess(`Deleted product "${name}"`);
      loadSavedProducts();
    } catch (err: any) {
      setError(err.message || 'Failed to delete product');
    }
  };

  const copyToClipboard = (text: string, id: string) => {
    navigator.clipboard.writeText(text);
    setCopiedLink(id);
    setTimeout(() => setCopiedLink(null), 2500);
  };

  const formatImg = (path?: string) => {
    if (!path) return '';
    let clean = path.replace(/\\/g, '/');
    if (clean.includes('/data/')) {
      clean = clean.substring(clean.indexOf('/data/'));
    } else if (clean.startsWith('data/')) {
      clean = `/${clean}`;
    }
    return clean.startsWith('/') ? clean : `/${clean}`;
  };

  const filteredSaved = savedProducts.filter((p) => {
    if (!savedFilter.trim()) return true;
    const term = savedFilter.toLowerCase();
    return (
      p.name.toLowerCase().includes(term) ||
      (p.brand && p.brand.toLowerCase().includes(term)) ||
      (p.product_truth?.asin && p.product_truth.asin.toLowerCase().includes(term))
    );
  });

  return (
    <div style={{ maxWidth: '1180px', margin: '0 auto', padding: '32px 24px' }}>

      {/* ── Page Header ─────────────────────────────── */}
      <div style={{ textAlign: 'center', marginBottom: '32px' }}>
        <div style={{
          display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
          width: '52px', height: '52px', borderRadius: '16px',
          background: 'linear-gradient(135deg, rgba(245,158,11,0.15), rgba(217,119,6,0.08))',
          border: '1px solid rgba(245,158,11,0.25)',
          marginBottom: '14px',
        }}>
          <Sparkles size={26} color="#f59e0b" />
        </div>
        <h1 style={{ fontSize: '1.8rem', fontWeight: 800, marginBottom: '6px' }}>
          Amazon Product Discovery & Importer
        </h1>
        <div style={{ display: 'flex', justifyContent: 'center', gap: '8px', alignItems: 'center', marginBottom: '8px' }}>
          <span className="badge" style={{
            background: 'rgba(245,158,11,0.12)', color: '#fbbf24',
            border: '1px solid rgba(245,158,11,0.3)', fontSize: '0.68rem',
            padding: '3px 10px',
          }}>
            LIVE US + IN ENGINE
          </span>
          <span style={{ width: '6px', height: '6px', borderRadius: '50%', background: '#10b981', boxShadow: '0 0 8px #10b981' }} />
        </div>
        <p style={{ color: 'var(--text-secondary)', fontSize: '0.92rem', maxWidth: '600px', margin: '0 auto' }}>
          Discover trending products, extract live reviews & prices, and import into your catalog with auto-generated country Smart Links.
        </p>
      </div>

      {/* ── Tab Switcher ───────────────────────────── */}
      <div style={{
        display: 'flex', gap: '6px', marginBottom: '28px',
        background: 'var(--bg-input)', padding: '5px',
        borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)',
        maxWidth: '560px', margin: '0 auto 28px auto',
      }}>
        <button
          onClick={() => setActiveTabState('search')}
          className="btn"
          style={{
            flex: 1, padding: '8px 14px', fontSize: '0.82rem', borderRadius: '8px',
            background: activeTab === 'search' ? 'linear-gradient(135deg, #f59e0b, #d97706)' : 'transparent',
            color: activeTab === 'search' ? '#09090b' : 'var(--text-secondary)',
            fontWeight: activeTab === 'search' ? 700 : 500,
            border: 'none', gap: '6px',
          }}
        >
          <Search size={14} />
          Live Trend Search
        </button>
        <button
          onClick={() => setActiveTabState('direct')}
          className="btn"
          style={{
            flex: 1, padding: '8px 14px', fontSize: '0.82rem', borderRadius: '8px',
            background: activeTab === 'direct' ? 'linear-gradient(135deg, #f59e0b, #d97706)' : 'transparent',
            color: activeTab === 'direct' ? '#09090b' : 'var(--text-secondary)',
            fontWeight: activeTab === 'direct' ? 700 : 500,
            border: 'none', gap: '6px',
          }}
        >
          <LinkIcon size={14} />
          Direct ASIN / Link
        </button>
        <button
          onClick={() => setActiveTabState('saved')}
          className="btn"
          style={{
            flex: 1, padding: '8px 14px', fontSize: '0.82rem', borderRadius: '8px',
            background: activeTab === 'saved' ? 'linear-gradient(135deg, #e60023, #ff334b)' : 'transparent',
            color: activeTab === 'saved' ? '#ffffff' : 'var(--text-secondary)',
            fontWeight: activeTab === 'saved' ? 700 : 500,
            border: 'none', gap: '6px',
          }}
        >
          <Layers size={14} />
          Saved Inventory ({savedProducts.length})
        </button>
      </div>

      {/* ── Success Banner ─────────────────────────── */}
      {successMsg && (
        <div className="glass-card" style={{
          padding: '12px 18px', marginBottom: '20px',
          background: 'rgba(16, 185, 129, 0.1)', borderColor: 'rgba(16, 185, 129, 0.3)',
          display: 'flex', alignItems: 'center', gap: '10px',
        }}>
          <CheckCircle size={18} color="#34d399" />
          <span style={{ color: '#34d399', fontSize: '0.88rem', fontWeight: 600 }}>{successMsg}</span>
        </div>
      )}

      {/* ── Error Banner ───────────────────────────── */}
      {error && (
        <div className="glass-card" style={{
          padding: '12px 18px', marginBottom: '20px',
          background: 'rgba(239, 68, 68, 0.08)', borderColor: 'rgba(239, 68, 68, 0.3)',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        }}>
          <span style={{ color: '#f87171', fontSize: '0.88rem' }}>{error}</span>
          <button onClick={() => setError(null)} className="btn btn-sm" style={{ background: 'transparent', border: 'none', color: '#f87171', padding: '4px' }}>
            <X size={16} />
          </button>
        </div>
      )}

      {/* ── TAB 1: Search ──────────────────────────── */}
      {activeTab === 'search' && (
        <div>
          {/* Search Bar */}
          <form onSubmit={(e) => { e.preventDefault(); handleSearch(query); }}
            style={{ display: 'flex', gap: '10px', marginBottom: '18px' }}
          >
            <div style={{ position: 'relative', flex: 1 }}>
              <Search size={16} style={{ position: 'absolute', left: '14px', top: '13px', color: 'var(--text-muted)' }} />
              <input
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search Amazon US products (e.g. vintage leather jacket, puff dress, ghost lamp)..."
                className="form-input"
                style={{ paddingLeft: '40px', height: '44px' }}
              />
            </div>
            <button
              type="submit"
              disabled={loading || !query.trim()}
              className="btn"
              style={{
                background: loading ? '#21262d' : 'linear-gradient(135deg, #f59e0b, #d97706)',
                color: loading ? 'var(--text-secondary)' : '#09090b',
                fontWeight: 700, border: 'none', padding: '0 24px', height: '44px',
                opacity: (!query.trim() || loading) ? 0.5 : 1,
                cursor: (!query.trim() || loading) ? 'not-allowed' : 'pointer',
                whiteSpace: 'nowrap',
              }}
            >
              {loading ? <Loader2 size={16} style={{ animation: 'spin 1s linear infinite' }} /> : <Search size={16} />}
              Search Amazon
            </button>
          </form>

          {/* Quick Trend Chips */}
          <div style={{ marginBottom: '24px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
              <TrendingUp size={14} color="#f59e0b" />
              <span style={{ fontSize: '0.78rem', fontWeight: 600, color: 'var(--text-secondary)' }}>
                Popular Pinterest Aesthetics:
              </span>
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
              {QUICK_TRENDS.map((t) => (
                <button
                  key={t}
                  type="button"
                  onClick={() => { setQuery(t); handleSearch(t); }}
                  className="btn btn-sm"
                  style={{
                    background: '#21262d', color: 'var(--text-secondary)',
                    border: '1px solid var(--border-subtle)',
                    fontSize: '0.76rem', padding: '4px 12px', fontWeight: 500,
                  }}
                >
                  {t}
                </button>
              ))}
            </div>
          </div>

          {/* Loading State */}
          {loading && (
            <div style={{ textAlign: 'center', padding: '60px 20px' }}>
              <Loader2 size={36} color="#f59e0b" style={{ animation: 'spin 1s linear infinite', margin: '0 auto 16px auto' }} />
              <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>Querying Amazon catalog & live ratings...</p>
            </div>
          )}

          {/* Results Grid */}
          {!loading && items.length > 0 && (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '14px' }}>
              {items.map((item) => {
                const isImported = importedAsins.has(item.asin);
                const isImporting = importingAsin === item.asin;

                return (
                  <div key={item.asin} className="glass-card" style={{
                    padding: '16px', display: 'flex', gap: '14px',
                    borderColor: isImported ? 'rgba(16, 185, 129, 0.3)' : 'var(--border-subtle)',
                    background: isImported ? 'rgba(16, 185, 129, 0.04)' : 'var(--bg-card)',
                  }}>
                    {/* Product Image */}
                    {item.primary_image_url ? (
                      <img
                        src={item.primary_image_url}
                        alt={item.title}
                        style={{
                          width: '80px', height: '96px', objectFit: 'cover',
                          borderRadius: 'var(--radius-md)', background: '#0d0f12',
                          flexShrink: 0, border: '1px solid var(--border-subtle)',
                        }}
                      />
                    ) : (
                      <div style={{
                        width: '80px', height: '96px', borderRadius: 'var(--radius-md)',
                        background: '#0d0f12', display: 'flex', alignItems: 'center',
                        justifyContent: 'center', flexShrink: 0, border: '1px solid var(--border-subtle)',
                      }}>
                        <Package size={24} color="var(--text-muted)" />
                      </div>
                    )}

                    {/* Product Details */}
                    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'space-between', minWidth: 0 }}>
                      <div>
                        <span style={{
                          fontSize: '0.65rem', fontFamily: 'monospace', fontWeight: 700,
                          padding: '2px 6px', background: '#21262d', borderRadius: '4px',
                          color: 'var(--text-secondary)',
                        }}>
                          {item.asin}
                        </span>
                        <h4 style={{
                          fontSize: '0.85rem', fontWeight: 700, marginTop: '5px',
                          color: 'var(--text-primary)', lineHeight: 1.35,
                          overflow: 'hidden', textOverflow: 'ellipsis',
                          display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical',
                        }} title={item.title}>
                          {item.title}
                        </h4>
                      </div>

                      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: '8px' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                          <span style={{ color: '#34d399', fontWeight: 800, fontSize: '0.92rem' }}>
                            {item.price || '$--'}
                          </span>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '3px' }}>
                            <Star size={12} fill="#fbbf24" color="#fbbf24" />
                            <span style={{ fontSize: '0.78rem', fontWeight: 600, color: '#fbbf24' }}>
                              {item.star_rating || '—'}
                            </span>
                            <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
                              ({item.review_count ? item.review_count.toLocaleString() : '—'})
                            </span>
                          </div>
                        </div>

                        <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
                          <a
                            href={`https://www.amazon.com/dp/${item.asin}`}
                            target="_blank"
                            rel="noreferrer"
                            className="btn btn-sm btn-secondary"
                            style={{ padding: '4px 8px', fontSize: '0.7rem', gap: '4px' }}
                            title="View on Amazon"
                          >
                            <ExternalLink size={11} />
                          </a>
                          <button
                            onClick={() => handleImportItem(item)}
                            disabled={isImported || isImporting}
                            className="btn btn-sm"
                            style={{
                              background: isImported
                                ? 'rgba(16, 185, 129, 0.15)'
                                : 'linear-gradient(135deg, #f59e0b, #d97706)',
                              color: isImported ? '#34d399' : '#09090b',
                              border: isImported ? '1px solid rgba(16, 185, 129, 0.3)' : 'none',
                              fontWeight: 700, padding: '5px 14px', fontSize: '0.76rem',
                              cursor: (isImported || isImporting) ? 'default' : 'pointer',
                              opacity: isImporting ? 0.6 : 1, gap: '5px',
                            }}
                          >
                            {isImporting ? (
                              <Loader2 size={13} style={{ animation: 'spin 1s linear infinite' }} />
                            ) : isImported ? (
                              <><CheckCircle size={13} /> Saved</>
                            ) : (
                              <><PackagePlus size={13} /> Save & Import</>
                            )}
                          </button>
                        </div>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          {/* Empty State */}
          {!loading && items.length === 0 && !error && (
            <div style={{ textAlign: 'center', padding: '60px 20px', color: 'var(--text-muted)' }}>
              <Search size={40} style={{ margin: '0 auto 16px auto', opacity: 0.3 }} />
              <p style={{ fontSize: '0.95rem', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '4px' }}>
                Search for any Amazon product above
              </p>
              <p style={{ fontSize: '0.82rem' }}>
                Or click one of the trending Pinterest aesthetic keywords to get started.
              </p>
            </div>
          )}
        </div>
      )}

      {/* ── TAB 2: Direct ASIN / URL Import ────────── */}
      {activeTab === 'direct' && (
        <div style={{ maxWidth: '560px', margin: '0 auto', paddingTop: '12px' }}>
          <div style={{ textAlign: 'center', marginBottom: '24px' }}>
            <div style={{
              display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
              width: '48px', height: '48px', borderRadius: '14px',
              background: 'rgba(245,158,11,0.1)', border: '1px solid rgba(245,158,11,0.2)',
              marginBottom: '12px',
            }}>
              <LinkIcon size={22} color="#f59e0b" />
            </div>
            <h3 style={{ fontSize: '1.1rem', fontWeight: 700, marginBottom: '6px' }}>
              Paste Any Amazon Product Link or ASIN
            </h3>
            <p style={{ fontSize: '0.82rem', color: 'var(--text-secondary)' }}>
              Supports full URLs (e.g. <span style={{ fontFamily: 'monospace', fontSize: '0.78rem', color: 'var(--text-link)' }}>amazon.com/dp/B08...</span>), short links, or raw 10-character ASINs.
            </p>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            <input
              type="text"
              value={directInput}
              onChange={(e) => setDirectInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') handleDirectImport(); }}
              placeholder="https://www.amazon.com/dp/B000GAWSDG or B000GAWSDG"
              className="form-input"
              style={{ height: '48px', fontSize: '0.9rem' }}
            />

            <button
              type="button"
              onClick={handleDirectImport}
              disabled={loading || !directInput.trim()}
              className="btn"
              style={{
                width: '100%', height: '48px',
                background: loading ? '#21262d' : 'linear-gradient(135deg, #f59e0b, #d97706)',
                color: loading ? 'var(--text-secondary)' : '#09090b',
                fontWeight: 700, fontSize: '0.9rem', border: 'none',
                opacity: (!directInput.trim() || loading) ? 0.5 : 1,
                cursor: (!directInput.trim() || loading) ? 'not-allowed' : 'pointer',
              }}
            >
              {loading ? (
                <><Loader2 size={16} style={{ animation: 'spin 1s linear infinite' }} /> Ingesting Product Data...</>
              ) : (
                <><Sparkles size={16} /> Fetch & Import to Inventory</>
              )}
            </button>
          </div>

          {/* Info Card */}
          <div className="glass-card" style={{ padding: '18px', marginTop: '24px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '10px' }}>
              <ShieldCheck size={16} color="#10b981" />
              <span style={{ fontSize: '0.82rem', fontWeight: 700, color: 'var(--text-primary)' }}>
                What happens when you import:
              </span>
            </div>
            <ul style={{
              listStyle: 'none', padding: 0, margin: 0,
              display: 'flex', flexDirection: 'column', gap: '7px',
            }}>
              {[
                'Downloads the original high-resolution product image locally to data/products',
                'Extracts real price, star rating, review count, and feature bullets',
                'Generates your universal Smart Link (/api/go) with your US & India affiliate tags',
                'Stores product in database ready for Creative Lab & Pin Composer',
              ].map((text, i) => (
                <li key={i} style={{ display: 'flex', alignItems: 'flex-start', gap: '8px', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                  <ArrowRight size={12} color="#f59e0b" style={{ marginTop: '3px', flexShrink: 0 }} />
                  {text}
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}

      {/* ── TAB 3: Saved Products Inventory ───────── */}
      {activeTab === 'saved' && (
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '18px', gap: '12px' }}>
            <div style={{ position: 'relative', flex: 1, maxWidth: '400px' }}>
              <Search size={15} style={{ position: 'absolute', left: '12px', top: '12px', color: 'var(--text-muted)' }} />
              <input
                type="text"
                value={savedFilter}
                onChange={(e) => setSavedFilter(e.target.value)}
                placeholder="Filter saved products by name, brand, ASIN..."
                className="form-input"
                style={{ paddingLeft: '36px', height: '38px', fontSize: '0.85rem' }}
              />
            </div>
            <span style={{ fontSize: '0.82rem', color: 'var(--text-secondary)', fontWeight: 600 }}>
              Showing {filteredSaved.length} of {savedProducts.length} saved products
            </span>
          </div>

          {loadingSaved && (
            <div style={{ textAlign: 'center', padding: '50px 20px' }}>
              <Loader2 size={32} color="#e60023" style={{ animation: 'spin 1s linear infinite', margin: '0 auto 12px auto' }} />
              <p style={{ color: 'var(--text-secondary)', fontSize: '0.88rem' }}>Loading saved product catalog...</p>
            </div>
          )}

          {!loadingSaved && filteredSaved.length > 0 && (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '14px' }}>
              {filteredSaved.map((product) => {
                const asin = product.product_truth?.asin || product.id.slice(0, 10);
                const truth = product.product_truth as any;
                const smartLink = product.affiliate_url || truth?.smart_affiliate_url || '';
                const isCopied = copiedLink === product.id;

                return (
                  <div key={product.id} className="glass-card" style={{
                    padding: '16px', display: 'flex', gap: '14px',
                    background: 'var(--bg-card)',
                  }}>
                    {/* Product Image */}
                    {product.product_image_path ? (
                      <img
                        src={formatImg(product.product_image_path)}
                        alt={product.name}
                        style={{
                          width: '84px', height: '100px', objectFit: 'cover',
                          borderRadius: 'var(--radius-md)', background: '#0d0f12',
                          flexShrink: 0, border: '1px solid var(--border-subtle)',
                        }}
                      />
                    ) : (
                      <div style={{
                        width: '84px', height: '100px', borderRadius: 'var(--radius-md)',
                        background: '#0d0f12', display: 'flex', alignItems: 'center',
                        justifyContent: 'center', flexShrink: 0, border: '1px solid var(--border-subtle)',
                      }}>
                        <Package size={24} color="var(--text-muted)" />
                      </div>
                    )}

                    {/* Product Details */}
                    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'space-between', minWidth: 0 }}>
                      <div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                          <span style={{
                            fontSize: '0.65rem', fontFamily: 'monospace', fontWeight: 700,
                            padding: '2px 6px', background: '#21262d', borderRadius: '4px',
                            color: 'var(--text-secondary)',
                          }}>
                            {asin}
                          </span>
                          <button
                            onClick={() => handleDeleteProduct(product.id, product.name)}
                            className="btn btn-sm"
                            style={{ background: 'transparent', border: 'none', color: 'var(--text-muted)', padding: '2px 4px' }}
                            title="Delete product"
                          >
                            <Trash2 size={13} />
                          </button>
                        </div>

                        <h4 style={{
                          fontSize: '0.85rem', fontWeight: 700, marginTop: '5px',
                          color: 'var(--text-primary)', lineHeight: 1.35,
                          overflow: 'hidden', textOverflow: 'ellipsis',
                          display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical',
                        }} title={product.name}>
                          {product.name}
                        </h4>
                      </div>

                      <div>
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: '6px', marginBottom: '8px' }}>
                          <span style={{ color: '#34d399', fontWeight: 800, fontSize: '0.92rem' }}>
                            {truth?.price_display || (product.price ? `$${product.price}` : '$--')}
                          </span>
                          {truth?.star_rating && (
                            <div style={{ display: 'flex', alignItems: 'center', gap: '3px' }}>
                              <Star size={12} fill="#fbbf24" color="#fbbf24" />
                              <span style={{ fontSize: '0.78rem', fontWeight: 600, color: '#fbbf24' }}>
                                {truth.star_rating}
                              </span>
                              {truth.review_count && (
                                <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
                                  ({truth.review_count.toLocaleString()})
                                </span>
                              )}
                            </div>
                          )}
                        </div>

                        {/* Action Buttons */}
                        <div style={{ display: 'flex', gap: '6px' }}>
                          {smartLink && (
                            <button
                              onClick={() => copyToClipboard(smartLink, product.id)}
                              className="btn btn-sm btn-secondary"
                              style={{ flex: 1, padding: '5px 8px', fontSize: '0.72rem', gap: '4px' }}
                              title="Copy Country Smart Affiliate Link"
                            >
                              {isCopied ? <Check size={12} color="#34d399" /> : <Copy size={12} />}
                              {isCopied ? 'Link Copied!' : 'Smart Link'}
                            </button>
                          )}
                          {setActiveTab && (
                            <button
                              onClick={() => {
                                if (setSelectedProductId) setSelectedProductId(product.id);
                                setActiveTab('lab');
                              }}
                              className="btn btn-sm btn-primary"
                              style={{ padding: '5px 12px', fontSize: '0.72rem', gap: '4px' }}
                              title="Send to Creative Lab & auto-compile prompt with real Amazon specs"
                            >
                              <Sparkle size={12} />
                              Generate Pin
                            </button>
                          )}
                        </div>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          {!loadingSaved && filteredSaved.length === 0 && (
            <div style={{ textAlign: 'center', padding: '60px 20px', color: 'var(--text-muted)' }}>
              <Package size={40} style={{ margin: '0 auto 16px auto', opacity: 0.3 }} />
              <p style={{ fontSize: '0.95rem', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '4px' }}>
                No saved products found
              </p>
              <p style={{ fontSize: '0.82rem' }}>
                Search Amazon in the Trend Search tab and click "Save & Import" to add products here.
              </p>
            </div>
          )}
        </div>
      )}

      {/* ── Footer Tags ────────────────────────────── */}
      <div style={{
        display: 'flex', justifyContent: 'center', alignItems: 'center', gap: '16px',
        marginTop: '36px', padding: '14px 0',
        borderTop: '1px solid var(--border-subtle)',
        fontSize: '0.75rem', color: 'var(--text-muted)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <span style={{ width: '6px', height: '6px', borderRadius: '50%', background: '#10b981', boxShadow: '0 0 6px #10b981' }} />
          US Tag: <span style={{ fontFamily: 'monospace', color: 'var(--text-secondary)' }}>nizamuddinsam-20</span>
        </div>
        <span>|</span>
        <div>
          IN Tag: <span style={{ fontFamily: 'monospace', color: 'var(--text-secondary)' }}>nizamuddins0a-21</span>
        </div>
        <span>|</span>
        <div>
          Dual-Engine: Creators API v3.1 + Smart Scraper
        </div>
      </div>
    </div>
  );
};
