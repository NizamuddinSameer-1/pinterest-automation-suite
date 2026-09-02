import React, { useState } from 'react';
import { BookOpen, ExternalLink, Network, FileText, CheckCircle2, GitBranch, Bug, Sparkles, RefreshCw } from 'lucide-react';

export const VaultHub: React.FC = () => {
  const [syncing, setSyncing] = useState<boolean>(false);
  const [syncMsg, setSyncMsg] = useState<string>('');

  const handleSyncVault = async () => {
    try {
      setSyncing(true);
      setSyncMsg('Synchronizing database entities with Obsidian Vault graph...');
      const res = await fetch('/api/vault/sync', { method: 'POST' }).then(r => r.json());
      if (res.status === 'success') {
        setSyncMsg('✅ Obsidian Vault fully synchronized with all Campaigns, Products, References, and Jobs!');
      } else {
        setSyncMsg('❌ Sync failed: ' + res.message);
      }
    } catch (e: any) {
      setSyncMsg('❌ Sync failed: ' + e.message);
    } finally {
      setSyncing(false);
      setTimeout(() => setSyncMsg(''), 6000);
    }
  };

  return (
    <div style={{ maxWidth: '1440px', margin: '0 auto', padding: '32px 24px' }}>
      {/* Header Banner */}
      <div style={{
        background: 'linear-gradient(135deg, rgba(168, 85, 247, 0.12), rgba(230, 0, 35, 0.08))',
        border: '1px solid var(--border-subtle)',
        borderRadius: 'var(--radius-xl)',
        padding: '28px 32px',
        marginBottom: '28px',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '16px', marginBottom: '8px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <BookOpen size={28} color="#a855f7" />
            <h1 style={{ fontSize: '1.75rem', fontWeight: 800 }}>Obsidian Knowledge Vault Hub</h1>
            <span className="badge badge-pass">Live Connected</span>
          </div>
          <button
            className="btn btn-primary"
            onClick={handleSyncVault}
            disabled={syncing}
            style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '10px 18px', fontSize: '0.88rem' }}
          >
            <RefreshCw size={16} className={syncing ? 'spin' : ''} />
            {syncing ? 'Syncing Graph...' : '⚡ Sync Vault Graph Now'}
          </button>
        </div>
        <p style={{ color: 'var(--text-secondary)', fontSize: '0.92rem' }}>
          Your project's history, prompt experiments, visual DNA, bug logs, and product truth constraints are mirrored in real time into your local Obsidian Vault.
        </p>
        {syncMsg && (
          <div style={{
            marginTop: '14px',
            padding: '10px 14px',
            background: syncMsg.startsWith('✅') ? 'rgba(16, 185, 129, 0.12)' : 'rgba(168, 85, 247, 0.12)',
            border: '1px solid var(--border-subtle)',
            borderRadius: 'var(--radius-md)',
            fontSize: '0.85rem',
            color: syncMsg.startsWith('✅') ? '#34d399' : '#c084fc',
            fontWeight: 600
          }}>
            {syncMsg}
          </div>
        )}
      </div>

      {/* Grid: 3 Explanatory Cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: '20px', marginBottom: '28px' }}>
        
        {/* Card 1: Graph View */}
        <div className="glass-card" style={{ padding: '24px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '14px' }}>
            <div style={{ padding: '8px', background: 'rgba(168, 85, 247, 0.1)', borderRadius: '8px', color: '#c084fc' }}>
              <Network size={20} />
            </div>
            <h3 style={{ fontSize: '1.05rem', fontWeight: 700 }}>Interactive Graph View</h3>
          </div>
          <p style={{ fontSize: '0.82rem', color: 'var(--text-secondary)', marginBottom: '16px', lineHeight: 1.6 }}>
            Open Obsidian and press <strong>Ctrl + G</strong> to view the live connected web of all your campaigns, products, references, prompts, and critiques.
          </p>
          <div style={{ padding: '10px 14px', background: 'var(--bg-input)', borderRadius: 'var(--radius-sm)', fontSize: '0.78rem', color: '#a855f7' }}>
            Path: <code>c:\Users\lenovo\OneDrive\Desktop\Pinterest Affilate System\vault</code>
          </div>
        </div>

        {/* Card 2: Auto Bug Logger */}
        <div className="glass-card" style={{ padding: '24px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '14px' }}>
            <div style={{ padding: '8px', background: 'rgba(239, 68, 68, 0.1)', borderRadius: '8px', color: '#f87171' }}>
              <Bug size={20} />
            </div>
            <h3 style={{ fontSize: '1.05rem', fontWeight: 700 }}>Automated Bug Logging</h3>
          </div>
          <p style={{ fontSize: '0.82rem', color: 'var(--text-secondary)', marginBottom: '16px', lineHeight: 1.6 }}>
            Any runtime exceptions or vision parsing timeouts automatically create a tagged <code>AUTO-BUG-*.md</code> note in <code>02 - Bugs & Issues/</code>.
          </p>
          <div style={{ padding: '10px 14px', background: 'var(--bg-input)', borderRadius: 'var(--radius-sm)', fontSize: '0.78rem', color: '#f87171' }}>
            Tags: <code>#bug/open</code> • <code>#severity/high</code>
          </div>
        </div>

        {/* Card 3: Ready-to-Use Templates */}
        <div className="glass-card" style={{ padding: '24px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '14px' }}>
            <div style={{ padding: '8px', background: 'rgba(16, 185, 129, 0.1)', borderRadius: '8px', color: '#34d399' }}>
              <FileText size={20} />
            </div>
            <h3 style={{ fontSize: '1.05rem', fontWeight: 700 }}>Pre-Built Templates</h3>
          </div>
          <p style={{ fontSize: '0.82rem', color: 'var(--text-secondary)', marginBottom: '16px', lineHeight: 1.6 }}>
            Use pre-configured templates in <code>07 - Templates/</code> to log new bug reports, dev notes, prompt experiments, and product truth sheets.
          </p>
          <div style={{ padding: '10px 14px', background: 'var(--bg-input)', borderRadius: 'var(--radius-sm)', fontSize: '0.78rem', color: '#34d399' }}>
            6 Production Templates Ready
          </div>
        </div>
      </div>

      {/* Directory Index Explorer */}
      <div className="glass-card" style={{ padding: '28px' }}>
        <h3 style={{ fontSize: '1.15rem', fontWeight: 700, marginBottom: '16px' }}>Vault Structure Index</h3>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '14px' }}>
          <div style={{ padding: '14px', background: 'var(--bg-input)', borderRadius: 'var(--radius-md)' }}>
            <strong style={{ fontSize: '0.85rem' }}>📁 00 - Dashboard & MOCs</strong>
            <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '4px' }}>
              Main Dashboard, Architecture MOC, Bug Tracker MOC, Visual DNA Hub
            </p>
          </div>
          <div style={{ padding: '14px', background: 'var(--bg-input)', borderRadius: 'var(--radius-md)' }}>
            <strong style={{ fontSize: '0.85rem' }}>📁 01 - Dev Logs & History</strong>
            <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '4px' }}>
              Daily Dev Logs, Project Roadmap, Milestones & Changelog
            </p>
          </div>
          <div style={{ padding: '14px', background: 'var(--bg-input)', borderRadius: 'var(--radius-md)' }}>
            <strong style={{ fontSize: '0.85rem' }}>📁 02 - Bugs & Issues</strong>
            <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '4px' }}>
              BUG-001, BUG-002, BUG-003, and automated bug incident reports
            </p>
          </div>
          <div style={{ padding: '14px', background: 'var(--bg-input)', borderRadius: 'var(--radius-md)' }}>
            <strong style={{ fontSize: '0.85rem' }}>📁 03 - Pipeline & Visual DNA</strong>
            <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '4px' }}>
              Live Reference Nodes, Visual DNA Library & Prompt Playbook
            </p>
          </div>
          <div style={{ padding: '14px', background: 'var(--bg-input)', borderRadius: 'var(--radius-md)' }}>
            <strong style={{ fontSize: '0.85rem' }}>📁 04 - Campaigns & Products</strong>
            <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '4px' }}>
              Campaign notes, Product Catalog, Truth Sheets & Pins
            </p>
          </div>
          <div style={{ padding: '14px', background: 'var(--bg-input)', borderRadius: 'var(--radius-md)' }}>
            <strong style={{ fontSize: '0.85rem' }}>📁 08 - Live Generation Nodes</strong>
            <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '4px' }}>
              Live Job Nodes, Prompt Version Histograms & Realism Critiques
            </p>
          </div>
        </div>
      </div>
    </div>
  );
};
