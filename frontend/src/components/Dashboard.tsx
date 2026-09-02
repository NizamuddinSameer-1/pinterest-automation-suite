import React, { useEffect, useState } from 'react';
import { api, Job } from '../api';
import { Sparkles, BookOpen } from 'lucide-react';

interface DashboardProps {
  setActiveTab: (tab: string) => void;
  setSelectedJobId?: (id: string) => void;
}

export const Dashboard: React.FC<DashboardProps> = ({ setActiveTab }) => {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    try {
      setLoading(true);
      const jData = await api.getJobs();
      setJobs(jData);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  // GENERATING is the state a Flow run sits in, so the "waiting on Flow" number
  // has to count both or the dashboard under-reports work in flight.
  const waitingFlow = jobs.filter(j => j.current_state === 'WAITING_FOR_FLOW' || j.current_state === 'GENERATING').length;
  const passedCritique = jobs.filter(j => j.current_state === 'PASS').length;
  const reworkCount = jobs.filter(j => j.current_state === 'REWORK').length;
  const outputsReady = jobs.filter(j => j.current_state === 'OUTPUT_UPLOADED').length;

  return (
    <div style={{ maxWidth: '1440px', margin: '0 auto', padding: '32px 24px' }}>
      {/* Header Banner */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        marginBottom: '32px',
        background: 'linear-gradient(135deg, rgba(230, 0, 35, 0.12), rgba(168, 85, 247, 0.08))',
        border: '1px solid var(--border-subtle)',
        borderRadius: 'var(--radius-xl)',
        padding: '28px 32px',
      }}>
        <div>
          <span className="badge badge-state" style={{ marginBottom: '10px' }}>Phase 1 Vertical Slice Live</span>
          <h1 style={{ fontSize: '1.85rem', fontWeight: 800, marginBottom: '6px' }}>Pinterest Realism Engine Cockpit</h1>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.95rem' }}>
            Turn casual Pinterest snapshots into authentic, high-CTR affiliate creatives through reverse-engineered photographic DNA.
          </p>
        </div>
        <div style={{ display: 'flex', gap: '12px' }}>
          <button
            onClick={() => setActiveTab('lab')}
            className="btn btn-primary"
            style={{ padding: '12px 22px', fontSize: '0.95rem' }}
          >
            <Sparkles size={18} />
            <span>Open Creative Lab</span>
          </button>
          <button
            onClick={() => setActiveTab('vault')}
            className="btn btn-secondary"
            style={{ padding: '12px 20px', fontSize: '0.95rem' }}
          >
            <BookOpen size={18} />
            <span>Obsidian Graph</span>
          </button>
        </div>
      </div>

      {/* Live job stats */}
      <div style={{ display: 'flex', gap: '16px', flexWrap: 'wrap', justifyContent: 'center', marginBottom: '24px' }}>
        {[
          { label: 'Total Jobs', value: jobs.length },
          { label: 'Generating / Waiting on Flow', value: waitingFlow },
          { label: 'Outputs Ready for Review', value: outputsReady },
          { label: 'Passed Critique', value: passedCritique },
          { label: 'In Rework', value: reworkCount },
        ].map(s => (
          <div key={s.label} style={{
            border: '1px solid var(--border-subtle)',
            borderRadius: 'var(--radius-xl)',
            padding: '18px 26px',
            minWidth: '180px',
            textAlign: 'center',
            background: 'var(--bg-primary)',
          }}>
            <div style={{ fontSize: '1.6rem', fontWeight: 800 }}>{loading ? '…' : s.value}</div>
            <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>{s.label}</div>
          </div>
        ))}
      </div>

      <div style={{ padding: '12px', textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.85rem' }}>
        Use <strong>Creative Lab</strong> to generate and <strong>Pin Composer</strong> to publish.
      </div>
    </div>
  );
};
