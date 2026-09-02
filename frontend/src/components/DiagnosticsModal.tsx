import React, { useState, useEffect } from 'react';
import { 
  Activity, CheckCircle2, AlertTriangle, XCircle, RefreshCw, 
  Terminal, ShieldCheck, Database, Cpu, Chrome, Compass, 
  HardDrive, FileCode, X, ArrowRight, Zap, ExternalLink 
} from 'lucide-react';
import { api } from '../api';

interface DiagnosticsModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export const DiagnosticsModal: React.FC<DiagnosticsModalProps> = ({ isOpen, onClose }) => {
  const [loading, setLoading] = useState(false);
  const [testing, setTesting] = useState<string | null>(null);
  const [diagnostics, setDiagnostics] = useState<any>(null);
  const [testResult, setTestResult] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);

  const fetchDiagnostics = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await api.getSystemStatus();
      setDiagnostics(data);
    } catch (err: any) {
      setError(err.message || 'Failed to run diagnostics');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (isOpen) {
      fetchDiagnostics();
    }
  }, [isOpen]);

  const handleTestLLM = async () => {
    try {
      setTesting('llm');
      const res = await api.testLLM();
      setTestResult({ title: 'LLM Provider Test', data: res });
      await fetchDiagnostics();
    } catch (err: any) {
      setTestResult({ title: 'LLM Provider Test', error: err.message });
    } finally {
      setTesting(null);
    }
  };

  const handleTestFlow = async () => {
    try {
      setTesting('flow');
      const res = await api.testFlowSession();
      setTestResult({ title: 'Google Flow Session Probe', data: res });
      await fetchDiagnostics();
    } catch (err: any) {
      setTestResult({ title: 'Google Flow Session Probe', error: err.message });
    } finally {
      setTesting(null);
    }
  };

  const handleTestPinterest = async () => {
    try {
      setTesting('pinterest');
      const res = await api.testPinterestSession();
      setTestResult({ title: 'Pinterest Session Probe', data: res });
      await fetchDiagnostics();
    } catch (err: any) {
      setTestResult({ title: 'Pinterest Session Probe', error: err.message });
    } finally {
      setTesting(null);
    }
  };

  if (!isOpen) return null;

  const subsystems = diagnostics?.subsystems || {};
  const overall = diagnostics?.overall_status || 'UNKNOWN';

  const renderStatusBadge = (status: string) => {
    if (status === 'PASS') {
      return (
        <span style={{ 
          display: 'inline-flex', alignItems: 'center', gap: '4px',
          background: 'rgba(16, 185, 129, 0.15)', color: '#34d399', 
          border: '1px solid rgba(16, 185, 129, 0.3)', padding: '3px 8px', borderRadius: '6px',
          fontSize: '0.72rem', fontWeight: 700
        }}>
          <CheckCircle2 size={13} /> PASS
        </span>
      );
    }
    if (status === 'WARN') {
      return (
        <span style={{ 
          display: 'inline-flex', alignItems: 'center', gap: '4px',
          background: 'rgba(245, 158, 11, 0.15)', color: '#fbbf24', 
          border: '1px solid rgba(245, 158, 11, 0.3)', padding: '3px 8px', borderRadius: '6px',
          fontSize: '0.72rem', fontWeight: 700
        }}>
          <AlertTriangle size={13} /> WARN
        </span>
      );
    }
    return (
      <span style={{ 
        display: 'inline-flex', alignItems: 'center', gap: '4px',
        background: 'rgba(239, 68, 68, 0.15)', color: '#f87171', 
        border: '1px solid rgba(239, 68, 68, 0.3)', padding: '3px 8px', borderRadius: '6px',
        fontSize: '0.72rem', fontWeight: 700
      }}>
        <XCircle size={13} /> FAIL
      </span>
    );
  };

  return (
    <div style={{
      position: 'fixed',
      inset: 0,
      background: 'rgba(5, 7, 10, 0.82)',
      backdropFilter: 'blur(12px)',
      zIndex: 100,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      padding: '24px',
    }}>
      <div style={{
        background: '#0d1117',
        border: '1px solid var(--border-subtle, #30363d)',
        borderRadius: '16px',
        width: '100%',
        maxWidth: '1000px',
        maxHeight: '90vh',
        display: 'flex',
        flexDirection: 'column',
        boxShadow: '0 24px 64px rgba(0, 0, 0, 0.6)',
        overflow: 'hidden',
      }}>
        {/* Header */}
        <div style={{
          padding: '20px 24px',
          borderBottom: '1px solid var(--border-subtle, #30363d)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          background: 'rgba(22, 27, 34, 0.6)',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <div style={{
              width: '36px', height: '36px', borderRadius: '10px',
              background: 'linear-gradient(135deg, #3b82f6, #6366f1)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              boxShadow: '0 4px 12px rgba(59, 130, 246, 0.3)'
            }}>
              <Activity size={20} color="#fff" />
            </div>
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <h2 style={{ fontSize: '1.15rem', fontWeight: 800, margin: 0, color: '#f0f6fc' }}>
                  System Diagnostics & Instant Debugger
                </h2>
                {renderStatusBadge(overall)}
              </div>
              <p style={{ fontSize: '0.75rem', color: '#8b949e', margin: '2px 0 0' }}>
                Live health, latency, error intelligence & root-cause advisor across all subsystems
              </p>
            </div>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <button
              onClick={fetchDiagnostics}
              disabled={loading}
              className="btn btn-secondary"
              style={{ padding: '6px 12px', fontSize: '0.8rem', display: 'flex', alignItems: 'center', gap: '6px' }}
            >
              <RefreshCw size={14} className={loading ? 'spin' : ''} />
              <span>{loading ? 'Inspecting...' : 'Refresh'}</span>
            </button>
            <button
              onClick={onClose}
              style={{
                background: 'transparent', border: 'none', color: '#8b949e',
                cursor: 'pointer', padding: '6px', borderRadius: '6px'
              }}
            >
              <X size={20} />
            </button>
          </div>
        </div>

        {/* Content Body */}
        <div style={{ padding: '24px', overflowY: 'auto', flex: 1, display: 'flex', flexDirection: 'column', gap: '20px' }}>
          
          {/* Quick Action Test Strip */}
          <div style={{
            display: 'flex', gap: '10px', flexWrap: 'wrap',
            background: '#161b22', padding: '12px 16px', borderRadius: '12px',
            border: '1px solid #30363d', alignItems: 'center', justifyContent: 'space-between'
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '0.8rem', color: '#8b949e' }}>
              <Zap size={15} color="#eab308" />
              <span>Instant Probes:</span>
            </div>
            <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
              <button
                onClick={handleTestLLM}
                disabled={testing !== null}
                className="btn btn-secondary"
                style={{ padding: '5px 12px', fontSize: '0.75rem', display: 'flex', alignItems: 'center', gap: '6px' }}
              >
                <Cpu size={14} />
                <span>{testing === 'llm' ? 'Probing...' : 'Test LLM'}</span>
              </button>
              <button
                onClick={handleTestFlow}
                disabled={testing !== null}
                className="btn btn-secondary"
                style={{ padding: '5px 12px', fontSize: '0.75rem', display: 'flex', alignItems: 'center', gap: '6px' }}
              >
                <Chrome size={14} />
                <span>{testing === 'flow' ? 'Probing...' : 'Test Google Flow'}</span>
              </button>
              <button
                onClick={handleTestPinterest}
                disabled={testing !== null}
                className="btn btn-secondary"
                style={{ padding: '5px 12px', fontSize: '0.75rem', display: 'flex', alignItems: 'center', gap: '6px' }}
              >
                <Compass size={14} />
                <span>{testing === 'pinterest' ? 'Probing...' : 'Test Pinterest'}</span>
              </button>
            </div>
          </div>

          {/* Test Probe Output Banner (if any) */}
          {testResult && (
            <div style={{
              background: testResult.error ? 'rgba(239, 68, 68, 0.1)' : 'rgba(59, 130, 246, 0.1)',
              border: `1px solid ${testResult.error ? 'rgba(239, 68, 68, 0.3)' : 'rgba(59, 130, 246, 0.3)'}`,
              padding: '12px 16px', borderRadius: '10px', fontSize: '0.8rem'
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontWeight: 700, marginBottom: '6px', color: testResult.error ? '#f87171' : '#60a5fa' }}>
                <span>⚡ {testResult.title} Result:</span>
                <button onClick={() => setTestResult(null)} style={{ background: 'transparent', border: 'none', color: '#8b949e', cursor: 'pointer' }}>
                  <X size={14} />
                </button>
              </div>
              <pre style={{ margin: 0, fontSize: '0.75rem', color: '#e6edf3', overflowX: 'auto' }}>
                {JSON.stringify(testResult.data || testResult.error, null, 2)}
              </pre>
            </div>
          )}

          {/* 6 Subsystem Cards Grid */}
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
            gap: '14px',
          }}>
            {/* 1. Database */}
            <div style={{
              background: '#161b22', border: '1px solid #30363d', borderRadius: '12px',
              padding: '16px', display: 'flex', flexDirection: 'column', gap: '8px'
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontWeight: 700, fontSize: '0.88rem' }}>
                  <Database size={16} color="#60a5fa" />
                  <span>Database</span>
                </div>
                {renderStatusBadge(subsystems.database?.status || 'UNKNOWN')}
              </div>
              <div style={{ fontSize: '0.75rem', color: '#8b949e', display: 'flex', flexDirection: 'column', gap: '3px' }}>
                <div>WAL Mode: <span style={{ color: '#e6edf3' }}>{subsystems.database?.details?.journal_mode || 'WAL'}</span> ({subsystems.database?.latency_ms || 0}ms)</div>
                <div>Records: <span style={{ color: '#e6edf3' }}>{subsystems.database?.details?.counts?.references || 0} refs, {subsystems.database?.details?.counts?.jobs || 0} jobs, {subsystems.database?.details?.counts?.pin_drafts || 0} pins</span></div>
              </div>
              {subsystems.database?.suggested_fix && (
                <div style={{ marginTop: 'auto', padding: '6px 8px', background: 'rgba(245, 158, 11, 0.1)', borderRadius: '6px', fontSize: '0.72rem', color: '#fbbf24' }}>
                  👉 {subsystems.database.suggested_fix}
                </div>
              )}
            </div>

            {/* 2. LLM Provider */}
            <div style={{
              background: '#161b22', border: '1px solid #30363d', borderRadius: '12px',
              padding: '16px', display: 'flex', flexDirection: 'column', gap: '8px'
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontWeight: 700, fontSize: '0.88rem' }}>
                  <Cpu size={16} color="#a78bfa" />
                  <span>LLM Provider Stack</span>
                </div>
                {renderStatusBadge(subsystems.llm_provider?.status || 'UNKNOWN')}
              </div>
              <div style={{ fontSize: '0.75rem', color: '#8b949e', display: 'flex', flexDirection: 'column', gap: '3px' }}>
                <div>Active Text Model: <span style={{ color: '#e6edf3' }}>{subsystems.llm_provider?.providers?.text_model || 'meta/llama-3.2-90b'}</span></div>
                <div>Latency: <span style={{ color: '#e6edf3' }}>{subsystems.llm_provider?.latency_ms || 0}ms</span></div>
              </div>
              {subsystems.llm_provider?.suggested_fix && (
                <div style={{ marginTop: 'auto', padding: '6px 8px', background: 'rgba(245, 158, 11, 0.1)', borderRadius: '6px', fontSize: '0.72rem', color: '#fbbf24' }}>
                  👉 {subsystems.llm_provider.suggested_fix}
                </div>
              )}
            </div>

            {/* 3. Google Flow Automation */}
            <div style={{
              background: '#161b22', border: '1px solid #30363d', borderRadius: '12px',
              padding: '16px', display: 'flex', flexDirection: 'column', gap: '8px'
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontWeight: 700, fontSize: '0.88rem' }}>
                  <Chrome size={16} color="#34d399" />
                  <span>Google Flow Browser</span>
                </div>
                {renderStatusBadge(subsystems.flow_automation?.status || 'UNKNOWN')}
              </div>
              <div style={{ fontSize: '0.75rem', color: '#8b949e', display: 'flex', flexDirection: 'column', gap: '3px' }}>
                <div>Profile: <span style={{ color: subsystems.flow_automation?.has_profile ? '#34d399' : '#f87171' }}>{subsystems.flow_automation?.has_profile ? 'Session Ready' : 'Not Logged In'}</span></div>
                <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>Project: {subsystems.flow_automation?.project_url}</div>
              </div>
              {subsystems.flow_automation?.suggested_fix && (
                <div style={{ marginTop: 'auto', padding: '6px 8px', background: 'rgba(245, 158, 11, 0.1)', borderRadius: '6px', fontSize: '0.72rem', color: '#fbbf24' }}>
                  👉 {subsystems.flow_automation.suggested_fix}
                </div>
              )}
            </div>

            {/* 4. Pinterest Publisher */}
            <div style={{
              background: '#161b22', border: '1px solid #30363d', borderRadius: '12px',
              padding: '16px', display: 'flex', flexDirection: 'column', gap: '8px'
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontWeight: 700, fontSize: '0.88rem' }}>
                  <Compass size={16} color="#f43f5e" />
                  <span>Pinterest Publisher</span>
                </div>
                {renderStatusBadge(subsystems.pinterest_publisher?.status || 'UNKNOWN')}
              </div>
              <div style={{ fontSize: '0.75rem', color: '#8b949e', display: 'flex', flexDirection: 'column', gap: '3px' }}>
                <div>Session Auth: <span style={{ color: subsystems.pinterest_publisher?.authenticated ? '#34d399' : '#f87171' }}>{subsystems.pinterest_publisher?.authenticated ? 'Authenticated' : 'Not Logged In'}</span></div>
                <div>Cached Boards: <span style={{ color: '#e6edf3' }}>{subsystems.pinterest_publisher?.cached_boards_count || 0} board(s) (Default: {subsystems.pinterest_publisher?.default_board})</span></div>
              </div>
              {subsystems.pinterest_publisher?.suggested_fix && (
                <div style={{ marginTop: 'auto', padding: '6px 8px', background: 'rgba(245, 158, 11, 0.1)', borderRadius: '6px', fontSize: '0.72rem', color: '#fbbf24' }}>
                  👉 {subsystems.pinterest_publisher.suggested_fix}
                </div>
              )}
            </div>

            {/* 5. Storage Assets */}
            <div style={{
              background: '#161b22', border: '1px solid #30363d', borderRadius: '12px',
              padding: '16px', display: 'flex', flexDirection: 'column', gap: '8px'
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontWeight: 700, fontSize: '0.88rem' }}>
                  <HardDrive size={16} color="#fbbf24" />
                  <span>Storage & Assets</span>
                </div>
                {renderStatusBadge(subsystems.storage?.status || 'UNKNOWN')}
              </div>
              <div style={{ fontSize: '0.75rem', color: '#8b949e', display: 'flex', flexDirection: 'column', gap: '3px' }}>
                <div>References: <span style={{ color: '#e6edf3' }}>{subsystems.storage?.counts?.references || 0} files</span></div>
                <div>Output Folders: <span style={{ color: '#e6edf3' }}>{subsystems.storage?.counts?.outputs || 0} folders</span></div>
              </div>
            </div>

            {/* 6. Obsidian Vault */}
            <div style={{
              background: '#161b22', border: '1px solid #30363d', borderRadius: '12px',
              padding: '16px', display: 'flex', flexDirection: 'column', gap: '8px'
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontWeight: 700, fontSize: '0.88rem' }}>
                  <FileCode size={16} color="#ec4899" />
                  <span>Obsidian Vault</span>
                </div>
                {renderStatusBadge(subsystems.vault?.status || 'UNKNOWN')}
              </div>
              <div style={{ fontSize: '0.75rem', color: '#8b949e', display: 'flex', flexDirection: 'column', gap: '3px' }}>
                <div>Connected: <span style={{ color: subsystems.vault?.connected ? '#34d399' : '#f87171' }}>{subsystems.vault?.connected ? 'Yes' : 'No'}</span></div>
                <div>Bug Notes Logged: <span style={{ color: '#e6edf3' }}>{subsystems.vault?.logged_bug_count || 0} note(s)</span></div>
              </div>
            </div>
          </div>

          {/* Recent Errors Section */}
          <div style={{
            background: '#161b22', border: '1px solid #30363d', borderRadius: '12px',
            padding: '16px', display: 'flex', flexDirection: 'column', gap: '10px'
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontWeight: 700, fontSize: '0.88rem', color: '#f0f6fc' }}>
              <Terminal size={16} color="#60a5fa" />
              <span>Recent Diagnostic Errors & Root-Cause Fixes</span>
            </div>

            {diagnostics?.recent_errors?.length > 0 ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                {diagnostics.recent_errors.map((err: any) => (
                  <div key={err.id} style={{
                    background: '#0d1117', border: '1px solid rgba(239, 68, 68, 0.25)',
                    borderRadius: '8px', padding: '12px', display: 'flex', flexDirection: 'column', gap: '6px'
                  }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <span style={{ fontWeight: 700, fontSize: '0.78rem', color: '#f87171' }}>
                        [{err.subsystem}] {err.error_type}
                      </span>
                      <span style={{ fontSize: '0.7rem', color: '#8b949e' }}>{err.location}</span>
                    </div>
                    <p style={{ margin: 0, fontSize: '0.75rem', color: '#e6edf3' }}>{err.message}</p>
                    {err.suggested_fix && (
                      <div style={{
                        marginTop: '4px', padding: '6px 10px', background: 'rgba(59, 130, 246, 0.1)',
                        borderLeft: '3px solid #3b82f6', borderRadius: '4px', fontSize: '0.72rem', color: '#93c5fd'
                      }}>
                        👉 <strong>Suggested Fix:</strong> {err.suggested_fix}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <div style={{
                display: 'flex', alignItems: 'center', gap: '8px', padding: '14px',
                background: 'rgba(16, 185, 129, 0.06)', borderRadius: '8px', color: '#34d399', fontSize: '0.78rem'
              }}>
                <CheckCircle2 size={16} />
                <span>All subsystems are healthy! No runtime errors currently recorded.</span>
              </div>
            )}
          </div>

        </div>

        {/* Footer */}
        <div style={{
          padding: '14px 24px', borderTop: '1px solid #30363d',
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          background: 'rgba(22, 27, 34, 0.6)', fontSize: '0.75rem', color: '#8b949e'
        }}>
          <div>CLI Tool Available: <code style={{ color: '#58a6ff' }}>python -m scripts.debug</code></div>
          <button onClick={onClose} className="btn btn-secondary" style={{ padding: '6px 14px' }}>
            Close
          </button>
        </div>

      </div>
    </div>
  );
};
