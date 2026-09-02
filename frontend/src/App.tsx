import React, { useState } from 'react';
import { Navbar } from './components/Navbar';
import { Dashboard } from './components/Dashboard';
import { CreativeLab } from './components/CreativeLab';
import { PinComposer } from './components/PinComposer';
import { ProductLibrary } from './components/ProductLibrary';
import { VaultHub } from './components/VaultHub';

export function App() {
  const [activeTab, setActiveTab] = useState<string>('dashboard');
  const [selectedJobId, setSelectedJobId] = useState<string | undefined>(undefined);
  const [selectedProductId, setSelectedProductId] = useState<string | undefined>(undefined);

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      <Navbar
        activeTab={activeTab}
        setActiveTab={setActiveTab}
      />

      <main style={{ flex: 1 }}>
        {activeTab === 'dashboard' && (
          <Dashboard 
            setActiveTab={setActiveTab} 
            setSelectedJobId={setSelectedJobId} 
          />
        )}
        {activeTab === 'lab' && (
          <CreativeLab 
            setActiveTab={setActiveTab} 
            selectedJobId={selectedJobId} 
            selectedProductId={selectedProductId}
            setSelectedProductId={setSelectedProductId}
          />
        )}
        {activeTab === 'pins' && (
          <PinComposer />
        )}
        {activeTab === 'products' && (
          <ProductLibrary 
            setActiveTab={setActiveTab} 
            setSelectedProductId={setSelectedProductId}
          />
        )}
        {activeTab === 'vault' && (
          <VaultHub />
        )}
      </main>

      {/* Footer */}
      <footer style={{
        borderTop: '1px solid var(--border-subtle)',
        padding: '20px 24px',
        background: 'var(--bg-primary)',
        marginTop: 'auto',
      }}>
        <div style={{
          maxWidth: '1440px',
          margin: '0 auto',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          fontSize: '0.78rem',
          color: 'var(--text-muted)'
        }}>
          <div>Pinterest Realism Engine (PRE) • Phase 1 Vertical Slice Live</div>
          <div style={{ display: 'flex', gap: '16px' }}>
            <span>Dual-Provider: OpenRouter + Gemini AI Studio</span>
            <span>•</span>
            <span>Obsidian Vault Connected</span>
          </div>
        </div>
      </footer>
    </div>
  );
}

export default App;
