import React, { useState } from 'react';
import { api, AmazonItem } from '../api';
import {
  Search,
  Sparkles,
  Link as LinkIcon,
  X,
  ExternalLink,
  Star,
  CheckCircle,
  Loader2,
  PackagePlus,
  TrendingUp,
  Tag,
  ShieldCheck,
} from 'lucide-react';

interface AmazonSearchModalProps {
  isOpen: boolean;
  onClose: () => void;
  onProductImported: (productId: string) => void;
}

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

export const AmazonSearchModal: React.FC<AmazonSearchModalProps> = ({
  isOpen,
  onClose,
  onProductImported,
}) => {
  const [activeTab, setActiveTab] = useState<'search' | 'direct'>('search');
  const [query, setQuery] = useState('');
  const [directInput, setDirectInput] = useState('');
  const [items, setItems] = useState<AmazonItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [importingAsin, setImportingAsin] = useState<string | null>(null);
  const [importedAsins, setImportedAsins] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);

  if (!isOpen) return null;

  const handleSearch = async (searchQuery: string) => {
    const q = searchQuery.trim();
    if (!q) return;
    setError(null);
    setLoading(true);
    try {
      const res = await api.searchAmazon(q, 'All', 8);
      if (res.success && res.items) {
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
        onProductImported(res.product_id);
        setTimeout(() => {
          onClose();
        }, 1200);
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
        onProductImported(res.product_id);
      }
    } catch (err: any) {
      setError(err.message || `Failed to import ${item.asin}`);
    } finally {
      setImportingAsin(null);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4 animate-in fade-in duration-200">
      <div className="bg-zinc-900 border border-zinc-700/80 rounded-2xl w-full max-w-4xl max-h-[90vh] flex flex-col shadow-2xl overflow-hidden text-zinc-100">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-zinc-800 bg-zinc-900/90">
          <div className="flex items-center gap-3">
            <div className="p-2.5 bg-amber-500/10 text-amber-400 border border-amber-500/20 rounded-xl">
              <Sparkles className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-lg font-semibold tracking-tight text-white flex items-center gap-2">
                Amazon Product Discovery & Importer
                <span className="text-[10px] uppercase font-bold tracking-wider px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-300 border border-amber-500/30">
                  Live US + IN Engine
                </span>
              </h2>
              <p className="text-xs text-zinc-400">
                Discover trending viral items or paste direct links to auto-generate UGC lookbooks & pins
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-2 text-zinc-400 hover:text-white rounded-lg hover:bg-zinc-800 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Tab Switcher */}
        <div className="flex border-b border-zinc-800 bg-zinc-950/40 px-6 pt-3 gap-6">
          <button
            onClick={() => setActiveTab('search')}
            className={`pb-3 text-sm font-medium transition-all relative flex items-center gap-2 ${
              activeTab === 'search'
                ? 'text-amber-400 border-b-2 border-amber-400'
                : 'text-zinc-400 hover:text-zinc-200'
            }`}
          >
            <Search className="w-4 h-4" />
            Live Trend Search
          </button>
          <button
            onClick={() => setActiveTab('direct')}
            className={`pb-3 text-sm font-medium transition-all relative flex items-center gap-2 ${
              activeTab === 'direct'
                ? 'text-amber-400 border-b-2 border-amber-400'
                : 'text-zinc-400 hover:text-zinc-200'
            }`}
          >
            <LinkIcon className="w-4 h-4" />
            Direct ASIN / Link Paste
          </button>
        </div>

        {/* Body Content */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          {/* TAB 1: Search */}
          {activeTab === 'search' && (
            <div className="space-y-4">
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  handleSearch(query);
                }}
                className="flex gap-2"
              >
                <div className="relative flex-1">
                  <Search className="absolute left-3.5 top-3.5 w-4 h-4 text-zinc-400" />
                  <input
                    type="text"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    placeholder="Search Amazon US products (e.g. vintage leather jacket, puff dress, ghost lamp)..."
                    className="w-full pl-10 pr-4 py-2.5 bg-zinc-800/80 border border-zinc-700 rounded-xl text-sm text-white placeholder-zinc-500 focus:outline-none focus:border-amber-400 focus:ring-1 focus:ring-amber-400 transition"
                  />
                </div>
                <button
                  type="submit"
                  disabled={loading || !query.trim()}
                  className="px-5 py-2.5 bg-amber-500 hover:bg-amber-400 disabled:opacity-50 text-zinc-950 font-semibold text-sm rounded-xl transition flex items-center gap-2 shadow-lg shadow-amber-500/10"
                >
                  {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Search className="w-4 h-4" />}
                  Search Amazon
                </button>
              </form>

              {/* Quick Trend Chips */}
              <div className="space-y-1.5">
                <div className="text-xs font-medium text-zinc-400 flex items-center gap-1.5">
                  <TrendingUp className="w-3.5 h-3.5 text-amber-400" />
                  Popular Pinterest Aesthetics:
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {QUICK_TRENDS.map((t) => (
                    <button
                      key={t}
                      type="button"
                      onClick={() => {
                        setQuery(t);
                        handleSearch(t);
                      }}
                      className="px-2.5 py-1 text-xs bg-zinc-800/60 hover:bg-zinc-700/80 border border-zinc-700/50 rounded-lg text-zinc-300 transition-all hover:text-white"
                    >
                      {t}
                    </button>
                  ))}
                </div>
              </div>

              {/* Results Grid */}
              {loading && (
                <div className="py-16 flex flex-col items-center justify-center text-center space-y-3">
                  <Loader2 className="w-8 h-8 animate-spin text-amber-400" />
                  <p className="text-sm text-zinc-400">Querying Amazon catalog & live ratings...</p>
                </div>
              )}

              {error && (
                <div className="p-4 bg-red-500/10 border border-red-500/30 rounded-xl text-sm text-red-400">
                  {error}
                </div>
              )}

              {!loading && items.length > 0 && (
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 pt-2">
                  {items.map((item) => {
                    const isImported = importedAsins.has(item.asin);
                    const isImporting = importingAsin === item.asin;

                    return (
                      <div
                        key={item.asin}
                        className="bg-zinc-800/50 border border-zinc-700/60 rounded-xl p-4 flex gap-4 hover:border-zinc-500/50 transition flex-col sm:flex-row justify-between"
                      >
                        <div className="flex gap-3">
                          {item.primary_image_url ? (
                            <img
                              src={item.primary_image_url}
                              alt={item.title}
                              className="w-20 h-24 object-cover rounded-lg bg-zinc-950 flex-shrink-0 border border-zinc-700/40"
                            />
                          ) : (
                            <div className="w-20 h-24 bg-zinc-900 rounded-lg flex items-center justify-center text-xs text-zinc-500">
                              No Image
                            </div>
                          )}
                          <div className="space-y-1 overflow-hidden">
                            <span className="text-[10px] font-mono font-bold px-1.5 py-0.5 bg-zinc-700/60 rounded text-zinc-300">
                              {item.asin}
                            </span>
                            <h3
                              className="text-xs font-semibold text-white line-clamp-2"
                              title={item.title}
                            >
                              {item.title}
                            </h3>
                            <div className="flex items-center gap-2 text-xs">
                              <span className="text-amber-400 font-bold">{item.price || '$29.99'}</span>
                              <span className="text-zinc-500">•</span>
                              <span className="flex items-center text-amber-300 font-medium">
                                <Star className="w-3 h-3 fill-amber-300 text-amber-300 mr-0.5" />
                                {item.star_rating || 4.8}
                              </span>
                              <span className="text-zinc-400 text-[11px]">
                                ({item.review_count ? item.review_count.toLocaleString() : '850'})
                              </span>
                            </div>
                          </div>
                        </div>

                        <div className="flex sm:flex-col justify-end gap-2 pt-2 sm:pt-0 border-t sm:border-t-0 border-zinc-700/40">
                          <button
                            onClick={() => handleImportItem(item)}
                            disabled={isImported || isImporting}
                            className={`px-3 py-2 text-xs font-semibold rounded-lg flex items-center justify-center gap-1.5 transition whitespace-nowrap ${
                              isImported
                                ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
                                : 'bg-amber-500 hover:bg-amber-400 text-zinc-950 shadow-md shadow-amber-500/10'
                            }`}
                          >
                            {isImporting ? (
                              <Loader2 className="w-3.5 h-3.5 animate-spin" />
                            ) : isImported ? (
                              <>
                                <CheckCircle className="w-3.5 h-3.5" /> Imported
                              </>
                            ) : (
                              <>
                                <PackagePlus className="w-3.5 h-3.5" /> 1-Click Import
                              </>
                            )}
                          </button>
                          <a
                            href={`https://www.amazon.com/dp/${item.asin}`}
                            target="_blank"
                            rel="noreferrer"
                            className="px-2 py-1 text-[11px] text-zinc-400 hover:text-zinc-200 text-center flex items-center justify-center gap-1"
                          >
                            View on Amazon <ExternalLink className="w-3 h-3" />
                          </a>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          )}

          {/* TAB 2: Direct ASIN / URL Import */}
          {activeTab === 'direct' && (
            <div className="space-y-6 max-w-xl mx-auto py-4">
              <div className="text-center space-y-2">
                <div className="inline-flex p-3 bg-amber-500/10 text-amber-400 rounded-2xl border border-amber-500/20 mb-2">
                  <LinkIcon className="w-6 h-6" />
                </div>
                <h3 className="text-base font-semibold text-white">
                  Paste Any Amazon Product Link or ASIN
                </h3>
                <p className="text-xs text-zinc-400">
                  Supports full URLs (e.g. <code>amazon.com/dp/B08...</code>), short links, or raw 10-character ASINs.
                </p>
              </div>

              <div className="space-y-3">
                <input
                  type="text"
                  value={directInput}
                  onChange={(e) => setDirectInput(e.target.value)}
                  placeholder="https://www.amazon.com/dp/B0G1X76GVQ or B0G1X76GVQ"
                  className="w-full px-4 py-3 bg-zinc-800/80 border border-zinc-700 rounded-xl text-sm text-white placeholder-zinc-500 focus:outline-none focus:border-amber-400 focus:ring-1 focus:ring-amber-400 transition"
                />

                <button
                  type="button"
                  onClick={handleDirectImport}
                  disabled={loading || !directInput.trim()}
                  className="w-full py-3 bg-amber-500 hover:bg-amber-400 disabled:opacity-50 text-zinc-950 font-bold text-sm rounded-xl transition flex items-center justify-center gap-2 shadow-lg shadow-amber-500/10"
                >
                  {loading ? (
                    <>
                      <Loader2 className="w-4 h-4 animate-spin" /> Ingesting Product Data...
                    </>
                  ) : (
                    <>
                      <Sparkles className="w-4 h-4" /> Fetch & Import to Studio
                    </>
                  )}
                </button>
              </div>

              {error && (
                <div className="p-4 bg-red-500/10 border border-red-500/30 rounded-xl text-sm text-red-400 text-center">
                  {error}
                </div>
              )}

              <div className="p-4 bg-zinc-800/30 border border-zinc-700/40 rounded-xl space-y-2 text-xs text-zinc-400">
                <div className="font-semibold text-zinc-300 flex items-center gap-1.5">
                  <ShieldCheck className="w-4 h-4 text-emerald-400" />
                  What happens when you import:
                </div>
                <ul className="list-disc list-inside space-y-1 text-zinc-400 pl-1">
                  <li>Downloads the original high-resolution product image automatically</li>
                  <li>Extracts real price, star rating, review count, and feature bullets</li>
                  <li>Generates your universal Smart Link (<code>/api/go</code>) with your US and India tags</li>
                  <li>Ready for 1-click Pin Composer & UGC Lookbook Generation</li>
                </ul>
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-3 border-t border-zinc-800 bg-zinc-950/40 flex justify-between items-center text-xs text-zinc-400">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span>
            US Tag: <span className="text-zinc-200 font-mono">nizamuddinsam-20</span> | IN Tag: <span className="text-zinc-200 font-mono">nizamuddins0a-21</span>
          </div>
          <button
            onClick={onClose}
            className="px-4 py-1.5 bg-zinc-800 hover:bg-zinc-700 rounded-lg text-zinc-200 transition"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
};
