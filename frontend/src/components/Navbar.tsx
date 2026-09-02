import React, { useState } from 'react';
import { Sparkles, Layers, Package, Pin, BookOpen, Activity, Terminal } from 'lucide-react';
import { DiagnosticsModal } from './DiagnosticsModal';

interface NavbarProps {
  activeTab: string;
  setActiveTab: (tab: string) => void;
  pendingFlowCount?: number;
  pendingReviewCount?: number;
}

export const Navbar: React.FC<NavbarProps> = ({
  activeTab,
  setActiveTab,
  pendingFlowCount = 0,
  pendingReviewCount = 0,
}) => {
  const [showDiagnostics, setShowDiagnostics] = useState(false);

  return (
    <header style={{
      borderBottom: '1px solid var(--border-subtle)',
      background: 'rgba(13, 15, 18, 0.85)',
      backdropFilter: 'blur(16px)',
      position: 'sticky',
      top: 0,
      zIndex: 50,
      padding: '0 24px',
    }}>
      <div style={{
        maxWidth: '1440px',
        margin: '0 auto',
        height: '64px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
      }}>
        {/* Brand */}
        <div 
          onClick={() => setActiveTab('dashboard')}
          style={{ display: 'flex', alignItems: 'center', gap: '10px', cursor: 'pointer' }}
        >
          <div style={{
            width: '36px',
            height: '36px',
            borderRadius: '10px',
            background: 'linear-gradient(135deg, #e60023, #ff334b)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            boxShadow: '0 4px 12px rgba(230, 0, 35, 0.4)'
          }}>
            <Sparkles size={20} color="#fff" />
          </div>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span style={{ fontWeight: 800, fontSize: '1.05rem', letterSpacing: '-0.02em' }}>Pinterest Realism Engine</span>
              <span className="badge" style={{ background: '#21262d', color: '#8b949e', border: '1px solid var(--border-subtle)' }}>v2.0</span>
            </div>
            <p style={{ fontSize: '0.72rem', color: 'var(--text-secondary)' }}>UGC Photographic DNA & Affiliate System</p>
          </div>
        </div>

        {/* Tab Switcher */}
        <nav style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <button
            onClick={() => setActiveTab('dashboard')}
            className={`btn ${activeTab === 'dashboard' ? 'btn-primary' : 'btn-secondary'}`}
            style={{ padding: '7px 14px' }}
          >
            <Layers size={16} />
            <span>Dashboard</span>
          </button>

          <button
            onClick={() => setActiveTab('lab')}
            className={`btn ${activeTab === 'lab' ? 'btn-primary' : 'btn-secondary'}`}
            style={{ padding: '7px 14px', position: 'relative' }}
          >
            <Sparkles size={16} />
            <span>Creative Lab</span>
            {pendingFlowCount > 0 && (
              <span style={{
                position: 'absolute',
                top: '-4px',
                right: '-4px',
                background: '#f59e0b',
                color: '#000',
                fontSize: '0.65rem',
                fontWeight: 800,
                width: '18px',
                height: '18px',
                borderRadius: '50%',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}>
                {pendingFlowCount}
              </span>
            )}
          </button>

          <button
            onClick={() => setActiveTab('pins')}
            className={`btn ${activeTab === 'pins' ? 'btn-primary' : 'btn-secondary'}`}
            style={{ padding: '7px 14px', position: 'relative' }}
          >
            <Pin size={16} />
            <span>Pin Composer</span>
            {pendingReviewCount > 0 && (
              <span style={{
                position: 'absolute',
                top: '-4px',
                right: '-4px',
                background: '#10b981',
                color: '#000',
                fontSize: '0.65rem',
                fontWeight: 800,
                width: '18px',
                height: '18px',
                borderRadius: '50%',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}>
                {pendingReviewCount}
              </span>
            )}
          </button>

          <button
            onClick={() => setActiveTab('products')}
            className={`btn ${activeTab === 'products' ? 'btn-primary' : 'btn-secondary'}`}
            style={{ padding: '7px 14px' }}
          >
            <Package size={16} />
            <span>Product Library</span>
          </button>

          <button
            onClick={() => setActiveTab('vault')}
            className={`btn ${activeTab === 'vault' ? 'btn-primary' : 'btn-secondary'}`}
            style={{ padding: '7px 14px' }}
          >
            <BookOpen size={16} />
            <span>Obsidian Vault</span>
          </button>
        </nav>

        {/* Live Diagnostics & System Indicators */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <button
            onClick={() => setShowDiagnostics(true)}
            className="btn btn-secondary"
            style={{
              padding: '6px 12px',
              fontSize: '0.75rem',
              fontWeight: 700,
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              border: '1px solid #3b82f6',
              background: 'rgba(59, 130, 246, 0.1)',
              color: '#60a5fa',
              cursor: 'pointer'
            }}
          >
            <Activity size={14} color="#60a5fa" />
            <span>Diagnostics</span>
          </button>

          <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            padding: '6px 12px',
            background: 'rgba(16, 185, 129, 0.08)',
            border: '1px solid rgba(16, 185, 129, 0.25)',
            borderRadius: '9999px',
            fontSize: '0.75rem',
            fontWeight: 600,
            color: '#34d399'
          }}>
            <div className="live-dot" />
            <span>Vault Synced</span>
          </div>
        </div>
      </div>

      {/* Diagnostics Modal */}
      <DiagnosticsModal 
        isOpen={showDiagnostics}
        onClose={() => setShowDiagnostics(false)}
      />
    </header>
  );
};

