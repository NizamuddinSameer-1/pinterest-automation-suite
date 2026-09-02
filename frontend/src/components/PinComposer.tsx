import React, { useState, useEffect, useRef } from 'react';
import { api, PinDraft, PinterestProfile, BulkSchedulePreview, BulkScheduleResult, BulkPinResult, PublishRun } from '../api';
import {
  Pin, Download, CheckCircle2, ShieldCheck, ExternalLink,
  Send, Calendar, Clock, Zap, RefreshCw,
  AlertCircle, Sparkles, Check, Eye, Copy, ArrowUpRight,
  Layers, ListChecks, CalendarClock, Edit3, CheckSquare, Square, Filter,
  Users, Plus, Trash2, Settings, ChevronDown
} from 'lucide-react';

/**
 * A `datetime-local` value for this moment in the operator's own timezone.
 */
function toLocalInputValue(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export const PinComposer: React.FC = () => {
  const [pins, setPins] = useState<PinDraft[]>([]);
  const [selectedPinIds, setSelectedPinIds] = useState<string[]>([]);
  const [activePinId, setActivePinId] = useState<string | null>(null);
  const [viewTab, setViewTab] = useState<'drafts' | 'scheduled' | 'published'>('drafts');
  const [loading, setLoading] = useState(false);
  const [statusMessage, setStatusMessage] = useState<{ text: string; type: 'success' | 'error' | 'info' } | null>(null);

  // ── Multiple Pinterest Profiles State ──
  const [profiles, setProfiles] = useState<PinterestProfile[]>([]);
  const [selectedProfileId, setSelectedProfileId] = useState<string>('default');
  const [accountsModalOpen, setAccountsModalOpen] = useState(false);
  const [newProfileName, setNewProfileName] = useState('');
  const [creatingProfile, setCreatingProfile] = useState(false);
  const [refreshingBoardsFor, setRefreshingBoardsFor] = useState<string | null>(null);
  const [accountBoards, setAccountBoards] = useState<Record<string, string[]>>({});

  // Per-Pin Local Edits Dictionary { [pinId]: { title, description, keywords, board_name, destination_url, profile_id } }
  const [pinEdits, setPinEdits] = useState<Record<string, {
    title: string;
    description: string;
    keywords: string;
    board_name: string;
    destination_url: string;
    profile_id: string;
  }>>({});
  const [savingEdit, setSavingEdit] = useState(false);

  // Bulk Apply Toolbar Values (to apply across all selected pins)
  const [bulkApplyProfile, setBulkApplyProfile] = useState('default');
  const [bulkApplyBoard, setBulkApplyBoard] = useState('');
  const [bulkApplyUrl, setBulkApplyUrl] = useState('');
  const [bulkApplyKeywords, setBulkApplyKeywords] = useState('');

  // Schedule Modal State (Single Pin)
  const [scheduleModalOpen, setScheduleModalOpen] = useState(false);
  const [scheduleDate, setScheduleDate] = useState(() => {
    const d = new Date();
    d.setHours(d.getHours() + 2, 0, 0, 0);
    return toLocalInputValue(d);
  });

  // ── Bulk scheduling through Pinterest's own scheduler ──
  const [bulkOpen, setBulkOpen] = useState(false);
  const [bulkSpacing, setBulkSpacing] = useState<'interval' | 'slots'>('interval');
  const [bulkStart, setBulkStart] = useState(() => {
    const d = new Date();
    d.setMinutes(d.getMinutes() + 45, 0, 0);
    return toLocalInputValue(d);
  });
  const [bulkInterval, setBulkInterval] = useState(60);
  const [bulkSlots, setBulkSlots] = useState('09:00, 13:00, 18:00, 21:00');
  const [bulkCap, setBulkCap] = useState<number | ''>('');
  const [bulkPreview, setBulkPreview] = useState<BulkSchedulePreview | null>(null);
  const [bulkPlanning, setBulkPlanning] = useState(false);
  const [bulkRunning, setBulkRunning] = useState(false);
  const [bulkResult, setBulkResult] = useState<BulkScheduleResult | null>(null);
  const [bulkError, setBulkError] = useState<string | null>(null);

  // ── The run in progress (Single or Batch Browser Publish) ──
  const [activeRun, setActiveRun] = useState<PublishRun | null>(null);
  const stopPolling = useRef(false);
  useEffect(() => () => { stopPolling.current = true; }, []);

  const followRun = async (runId: string): Promise<PublishRun | null> => {
    let misses = 0;
    for (let tick = 0; !stopPolling.current; tick++) {
      await new Promise((r) => setTimeout(r, tick === 0 ? 1200 : 3000));
      if (stopPolling.current) return null;
      let run: PublishRun;
      try {
        run = await api.getPublishRun(runId);
        misses = 0;
      } catch (e: any) {
        if (++misses >= 5) {
          showStatus(
            `Lost contact with backend publisher (${e.message}). The browser run continues in background.`,
            'error'
          );
          return null;
        }
        continue;
      }
      setActiveRun(run);
      if (run.stalled || run.status === 'done' || run.status === 'error') return run;
    }
    return null;
  };

  useEffect(() => {
    loadProfiles();
    loadPins();
  }, []);

  const showStatus = (text: string, type: 'success' | 'error' | 'info' = 'success') => {
    setStatusMessage({ text, type });
    setTimeout(() => setStatusMessage(null), 8000);
  };

  const loadProfiles = async () => {
    try {
      const data = await api.getPinterestProfiles();
      setProfiles(data || []);
      if (data && data.length > 0) {
        const def = data.find((p) => p.is_default) || data[0];
        setSelectedProfileId(def.id);
        setBulkApplyProfile(def.id);
        data.forEach((p) => {
          loadBoardsForProfile(p.id);
        });
      }
    } catch (e) {
      console.error('Failed to load Pinterest profiles:', e);
    }
  };

  const loadBoardsForProfile = async (profileId: string) => {
    try {
      const data = await api.getAccountBoards(profileId);
      if (data && Array.isArray(data.boards)) {
        setAccountBoards((prev) => ({
          ...prev,
          [profileId]: data.boards,
        }));
      }
    } catch (e) {
      console.error(`Failed to load boards for profile ${profileId}:`, e);
    }
  };

  const loadPins = async () => {
    try {
      setLoading(true);
      const data = await api.getPins();
      setPins(data || []);

      // Initialize local edits for each pin if not present
      setPinEdits((prev) => {
        const next = { ...prev };
        data.forEach((p) => {
          if (!next[p.id]) {
            next[p.id] = {
              title: p.title || '',
              description: p.description || '',
              keywords: Array.isArray(p.keywords) ? p.keywords.join(', ') : '',
              board_name: p.board_name || '',
              destination_url: p.destination_url || '',
              profile_id: p.profile_id || 'default',
            };
          }
        });
        return next;
      });

      // Default selection
      if (data.length > 0) {
        if (selectedPinIds.length === 0) {
          const firstJobId = data[0].job_id;
          const firstBatch = data.filter((p) => p.job_id === firstJobId && p.status !== 'published');
          if (firstBatch.length > 0) {
            setSelectedPinIds(firstBatch.map((p) => p.id));
            setActivePinId(firstBatch[0].id);
          } else {
            setSelectedPinIds([data[0].id]);
            setActivePinId(data[0].id);
          }
        }
      }
    } catch (e: any) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  // ── Profile Management Actions ──
  const handleLaunchProfileLogin = async (profileId: string) => {
    try {
      const prof = profiles.find((p) => p.id === profileId);
      showStatus(`🌐 Opening Chrome login window for "${prof?.name || profileId}"...`, 'info');
      await api.launchPinterestAuth(profileId);
      showStatus(`👉 Log into Pinterest in Chrome, then press ENTER in the terminal console popup.`, 'info');
      setTimeout(loadProfiles, 8000);
    } catch (e: any) {
      showStatus(`Login launch failed: ${e.message}`, 'error');
    }
  };

  const handleRefreshBoardsForProfile = async (profileId: string) => {
    try {
      setRefreshingBoardsFor(profileId);
      showStatus(`🔄 Refreshing board list from Pinterest for profile "${profileId}"...`, 'info');
      await api.refreshAccountBoards(profileId);
      setTimeout(async () => {
        await loadBoardsForProfile(profileId);
        await loadProfiles();
        setRefreshingBoardsFor(null);
        showStatus(`✅ Board list updated!`, 'success');
      }, 6000);
    } catch (e: any) {
      setRefreshingBoardsFor(null);
      showStatus(`Board refresh failed: ${e.message}`, 'error');
    }
  };

  const handleCreateProfile = async () => {
    if (!newProfileName.trim()) return;
    try {
      setCreatingProfile(true);
      const created = await api.createPinterestProfile(newProfileName.trim());
      setNewProfileName('');
      await loadProfiles();
      showStatus(`🎉 Created profile "${created.name}"! Opening login window...`, 'success');
      await handleLaunchProfileLogin(created.id);
    } catch (e: any) {
      showStatus(`Failed to create profile: ${e.message}`, 'error');
    } finally {
      setCreatingProfile(false);
    }
  };

  const handleDeleteProfile = async (profileId: string) => {
    if (!window.confirm(`Are you sure you want to delete this profile? Stored cookies will be removed.`)) return;
    try {
      await api.deletePinterestProfile(profileId);
      await loadProfiles();
      showStatus(`Deleted profile successfully.`, 'info');
    } catch (e: any) {
      showStatus(`Delete failed: ${e.message}`, 'error');
    }
  };

  // Helper to get edit fields for a pin
  const getPinEdit = (pin: PinDraft) => {
    return pinEdits[pin.id] || {
      title: pin.title || '',
      description: pin.description || '',
      keywords: Array.isArray(pin.keywords) ? pin.keywords.join(', ') : '',
      board_name: pin.board_name || '',
      destination_url: pin.destination_url || '',
      profile_id: pin.profile_id || 'default',
    };
  };

  const updatePinEdit = (pinId: string, field: string, value: string) => {
    setPinEdits((prev) => ({
      ...prev,
      [pinId]: {
        ...(prev[pinId] || { title: '', description: '', keywords: '', board_name: '', destination_url: '', profile_id: 'default' }),
        [field]: value,
      },
    }));
  };

  // Toggle selection of a single pin
  const toggleSelectPin = (pinId: string) => {
    setBulkPreview(null);
    setBulkResult(null);
    setSelectedPinIds((prev) => {
      if (prev.includes(pinId)) {
        const next = prev.filter((id) => id !== pinId);
        if (activePinId === pinId) {
          setActivePinId(next.length > 0 ? next[0] : null);
        }
        return next;
      } else {
        setActivePinId(pinId);
        return [...prev, pinId];
      }
    });
  };

  // Filter pins by Tab
  const SCHEDULED_STATES = ['scheduled', 'scheduled_pinterest'];
  const filteredPins = pins.filter((p) => {
    if (viewTab === 'drafts') return !SCHEDULED_STATES.includes(p.status) && p.status !== 'published';
    if (viewTab === 'scheduled') return SCHEDULED_STATES.includes(p.status);
    if (viewTab === 'published') return p.status === 'published';
    return true;
  });

  const bulkCandidates = pins.filter((p) => !SCHEDULED_STATES.includes(p.status) && p.status !== 'published');

  const handleSelectAllDrafts = () => {
    const draftIds = bulkCandidates.map((p) => p.id);
    setSelectedPinIds(draftIds);
    if (draftIds.length > 0 && (!activePinId || !draftIds.includes(activePinId))) {
      setActivePinId(draftIds[0]);
    }
  };

  const handleClearSelection = () => {
    setSelectedPinIds([]);
    setActivePinId(null);
  };

  // Bulk Apply Properties across all selected pins
  const handleBulkApplyProfile = () => {
    if (!bulkApplyProfile) return;
    setPinEdits((prev) => {
      const next = { ...prev };
      selectedPinIds.forEach((id) => {
        if (next[id]) {
          next[id] = { ...next[id], profile_id: bulkApplyProfile };
        }
      });
      return next;
    });
    const prof = profiles.find((p) => p.id === bulkApplyProfile);
    showStatus(`👤 Assigned "${prof?.name || bulkApplyProfile}" to ${selectedPinIds.length} selected pin(s). Click Save to store!`);
  };

  const handleBulkApplyBoard = () => {
    if (!bulkApplyBoard.trim()) return;
    setPinEdits((prev) => {
      const next = { ...prev };
      selectedPinIds.forEach((id) => {
        if (next[id]) {
          next[id] = { ...next[id], board_name: bulkApplyBoard.trim() };
        }
      });
      return next;
    });
    showStatus(`📌 Applied board "${bulkApplyBoard.trim()}" to ${selectedPinIds.length} selected pin(s). Click Save to store!`);
  };

  const handleBulkApplyUrl = () => {
    if (!bulkApplyUrl.trim()) return;
    setPinEdits((prev) => {
      const next = { ...prev };
      selectedPinIds.forEach((id) => {
        if (next[id]) {
          next[id] = { ...next[id], destination_url: bulkApplyUrl.trim() };
        }
      });
      return next;
    });
    showStatus(`🔗 Applied destination URL to ${selectedPinIds.length} selected pin(s).`);
  };

  const handleBulkApplyKeywords = () => {
    if (!bulkApplyKeywords.trim()) return;
    setPinEdits((prev) => {
      const next = { ...prev };
      selectedPinIds.forEach((id) => {
        if (next[id]) {
          next[id] = { ...next[id], keywords: bulkApplyKeywords.trim() };
        }
      });
      return next;
    });
    showStatus(`🏷️ Applied keywords to ${selectedPinIds.length} selected pin(s).`);
  };

  // Save all modified pins
  const handleSaveAllSelectedPins = async () => {
    try {
      setSavingEdit(true);
      const targets = selectedPinIds.length > 0 ? selectedPinIds : (activePinId ? [activePinId] : []);
      if (targets.length === 0) return;

      for (const pinId of targets) {
        const edits = pinEdits[pinId];
        if (!edits) continue;
        const kwArray = edits.keywords.split(',').map((k) => k.trim()).filter(Boolean);
        await fetch(`/api/pins/${pinId}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            title: edits.title,
            description: edits.description,
            keywords: kwArray,
            board_name: edits.board_name,
            destination_url: edits.destination_url,
            profile_id: edits.profile_id,
          }),
        });
      }
      showStatus(`✅ Saved metadata & accounts for ${targets.length} pin(s) successfully!`);
      await loadPins();
    } catch (e: any) {
      showStatus(`Save failed: ${e.message}`, 'error');
    } finally {
      setSavingEdit(false);
    }
  };

  // ── 1. Batch Publish All Selected Pins at Once ──
  const handleBatchPublishAll = async () => {
    const targets = selectedPinIds.filter((id) => {
      const p = pins.find((x) => x.id === id);
      return p && p.status !== 'published';
    });

    if (targets.length === 0) {
      showStatus('Please select at least 1 unpublished pin draft to publish.', 'error');
      return;
    }

    try {
      setLoading(true);
      setActiveRun(null);

      // Auto save pending edits first
      await handleSaveAllSelectedPins();

      showStatus(
        `🚀 Launching Autonomous Browser to publish all ${targets.length} selected pin(s)... Chrome is opening.`,
        'info'
      );

      const started = await api.bulkPublishPins({
        pin_ids: targets,
        profile_id: selectedProfileId,
        allow_no_link: false,
        force_board: false,
        headless: false,
      });

      const run = started.run_id ? await followRun(started.run_id) : null;
      await loadPins();

      if (!run) return;

      if (run.status === 'done' || (run.completed > 0 && run.completed === run.total)) {
        const publishedCount = run.results.filter((r) => r.status === 'published').length;
        showStatus(`🎉 Successfully published ${publishedCount} of ${targets.length} pin(s) to Pinterest!`, 'success');
      } else if (run.status === 'error') {
        showStatus(`Publisher finished with issues: ${run.error || 'Check status below.'}`, 'error');
      }
    } catch (e: any) {
      showStatus(`Batch publish failed: ${e.message}`, 'error');
    } finally {
      setLoading(false);
    }
  };

  // ── 2. Publish Single Pin Immediately ──
  const handlePublishSinglePin = async (pinId: string) => {
    try {
      setLoading(true);
      setActiveRun(null);

      const edits = pinEdits[pinId];
      if (edits) {
        const kwArray = edits.keywords.split(',').map((k) => k.trim()).filter(Boolean);
        await fetch(`/api/pins/${pinId}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            title: edits.title,
            description: edits.description,
            keywords: kwArray,
            board_name: edits.board_name,
            destination_url: edits.destination_url,
            profile_id: edits.profile_id,
          }),
        });
      }

      const targetProf = edits?.profile_id || 'default';
      const profObj = profiles.find((p) => p.id === targetProf);
      showStatus(`🚀 Starting browser publisher for this pin (Target: ${profObj?.name || targetProf})...`, 'info');
      const started = await api.publishPin(pinId, targetProf);
      const run = await followRun(started.run_id);
      await loadPins();

      if (!run) return;
      const res = run.results.find((r) => r.pin_id === pinId);
      if (res?.live_url) {
        showStatus(`🎉 Published live: ${res.live_url}`, 'success');
      } else if (res?.confirmed_by) {
        showStatus(`Pinterest confirmed pin (${res.confirmed_by})!`, 'success');
      } else if (res?.error) {
        showStatus(`Publish failed: ${res.error}`, 'error');
      }
    } catch (e: any) {
      showStatus(`Publish failed: ${e.message}`, 'error');
    } finally {
      setLoading(false);
    }
  };

  // ── 3. Bulk Native Scheduling ──
  const bulkOptions = () => {
    const slots = bulkSlots.split(',').map((s) => s.trim()).filter(Boolean);
    return {
      pin_ids: selectedPinIds,
      profile_id: selectedProfileId,
      start_time: bulkStart,
      interval_minutes: bulkSpacing === 'interval' ? Number(bulkInterval) : undefined,
      daily_slots: bulkSpacing === 'slots' ? slots : undefined,
      per_day_cap: bulkCap === '' ? undefined : Number(bulkCap),
      headless: false,
    };
  };

  const handleBulkPreview = async () => {
    if (selectedPinIds.length === 0) {
      setBulkError('Select at least one pin to schedule.');
      return;
    }
    try {
      setBulkPlanning(true);
      setBulkError(null);
      setBulkResult(null);
      const preview = await api.previewBulkSchedule(bulkOptions());
      setBulkPreview(preview);
    } catch (e: any) {
      setBulkPreview(null);
      setBulkError(e.message || 'Could not plan those times');
    } finally {
      setBulkPlanning(false);
    }
  };

  const handleBulkSchedule = async () => {
    if (!bulkPreview) {
      setBulkError('Preview the times first, then schedule.');
      return;
    }
    try {
      setBulkRunning(true);
      setBulkError(null);
      setActiveRun(null);
      showStatus(`📅 Scheduling ${bulkPreview.count} pin(s) on Pinterest... Chrome is driving the batch.`, 'info');
      const started = await api.bulkSchedulePins(bulkOptions());
      const run = started.run_id ? await followRun(started.run_id) : null;
      await loadPins();
      if (!run) {
        setBulkRunning(false);
        return;
      }

      const scheduled = run.results.filter((r) => r.status === 'scheduled');
      const failed = run.results.filter((r) => r.status === 'failed');
      setBulkResult({
        ...started,
        scheduled: scheduled.length,
        failed: failed.length,
        results: run.results,
      });
      if (scheduled.length > 0) {
        showStatus(`🎉 ${scheduled.length} pin(s) queued on Pinterest!`, 'success');
      }
      if (failed.length > 0) {
        showStatus(`${failed.length} pin(s) failed. Check details below.`, 'error');
      }
    } catch (e: any) {
      setBulkError(e.message || 'Bulk schedule failed');
    } finally {
      setBulkRunning(false);
    }
  };

  const activePin = pins.find((p) => p.id === activePinId);
  const activePinEdit = activePin ? getPinEdit(activePin) : null;
  const selectedPinsList = pins.filter((p) => selectedPinIds.includes(p.id));
  const authenticatedCount = profiles.filter((p) => p.authenticated).length;

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'published':
        return <span className="badge badge-success">Live on Pinterest</span>;
      case 'scheduled':
      case 'scheduled_pinterest':
        return <span className="badge badge-warning">Pinterest Scheduled</span>;
      case 'draft':
      default:
        return <span className="badge badge-neutral">Ready to Publish</span>;
    }
  };

  const renderRunProgress = (run: PublishRun) => {
    const pct = run.total > 0 ? Math.round((run.completed / run.total) * 100) : 0;
    return (
      <div
        className="glass-card"
        style={{
          padding: '16px 20px',
          marginBottom: '20px',
          border: '1px solid rgba(230,0,35,0.4)',
          background: 'linear-gradient(135deg, rgba(230,0,35,0.08), rgba(99,102,241,0.08))',
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Zap size={16} color="#e60023" />
            <strong style={{ fontSize: '0.9rem' }}>
              Publish Run in Progress ({run.completed}/{run.total} Pins)
            </strong>
          </div>
          <span style={{ fontSize: '0.8rem', fontWeight: 700, color: 'var(--text-muted)' }}>
            {pct}%
          </span>
        </div>
        <div style={{ width: '100%', height: '6px', background: 'rgba(255,255,255,0.1)', borderRadius: '3px', overflow: 'hidden' }}>
          <div style={{ width: `${pct}%`, height: '100%', background: 'linear-gradient(90deg, #e60023, #ff4757)', transition: 'width 0.3s ease' }} />
        </div>
      </div>
    );
  };

  return (
    <div style={{ maxWidth: '1440px', margin: '0 auto', paddingBottom: '60px' }}>
      {/* ── Top Header ── */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px', flexWrap: 'wrap', gap: '12px' }}>
        <div>
          <h1 style={{ fontSize: '1.8rem', fontWeight: 800, margin: '0 0 4px', display: 'flex', alignItems: 'center', gap: '10px' }}>
            <Pin color="#e60023" size={28} />
            <span>Pin Composer & Direct Publisher</span>
          </h1>
          <p style={{ margin: 0, color: 'var(--text-secondary)', fontSize: '0.88rem' }}>
            Review visual variations, assign Pinterest accounts, tune SEO metadata, and publish directly.
          </p>
        </div>

        {/* Top Bar Actions & Profiles Pill */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
          {/* Multi-Profile Session Trigger */}
          <div
            onClick={() => setAccountsModalOpen(true)}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              padding: '6px 14px',
              background: authenticatedCount > 0 ? 'rgba(16, 185, 129, 0.12)' : 'rgba(230, 0, 35, 0.12)',
              border: `1px solid ${authenticatedCount > 0 ? 'rgba(16, 185, 129, 0.3)' : 'rgba(230, 0, 35, 0.3)'}`,
              borderRadius: 'var(--radius-md)',
              cursor: 'pointer',
              fontSize: '0.82rem',
              fontWeight: 600,
              color: authenticatedCount > 0 ? '#34d399' : '#ff4757',
              transition: 'all 0.2s',
            }}
            title="Click to manage Pinterest accounts & sessions"
          >
            <div
              style={{
                width: '8px',
                height: '8px',
                borderRadius: '50%',
                background: authenticatedCount > 0 ? '#10b981' : '#e60023',
                boxShadow: authenticatedCount > 0 ? '0 0 8px #10b981' : '0 0 8px #e60023',
              }}
            />
            <span>
              {profiles.length > 1
                ? `${authenticatedCount}/${profiles.length} Accounts Connected`
                : (authenticatedCount > 0 ? 'Pinterest Account Active' : '🔑 Connect Pinterest Account')}
            </span>
            <ChevronDown size={13} style={{ opacity: 0.8 }} />
          </div>

          <button
            onClick={() => { loadProfiles(); loadPins(); }}
            className="btn btn-secondary btn-sm"
            title="Refresh Pins"
          >
            <RefreshCw size={14} className={loading ? 'spin' : ''} />
            <span>Refresh</span>
          </button>
        </div>
      </div>

      {/* ── Status Toast ── */}
      {statusMessage && (
        <div
          style={{
            marginBottom: '20px',
            padding: '12px 18px',
            background: statusMessage.type === 'success' ? 'rgba(16, 185, 129, 0.15)' : (statusMessage.type === 'error' ? 'rgba(239, 68, 68, 0.15)' : 'rgba(59, 130, 246, 0.15)'),
            border: `1px solid ${statusMessage.type === 'success' ? 'rgba(16, 185, 129, 0.4)' : (statusMessage.type === 'error' ? 'rgba(239, 68, 68, 0.4)' : 'rgba(59, 130, 246, 0.4)')}`,
            borderRadius: 'var(--radius-md)',
            color: statusMessage.type === 'success' ? '#34d399' : (statusMessage.type === 'error' ? '#f87171' : '#60a5fa'),
            fontWeight: 600,
            fontSize: '0.88rem',
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
          }}
        >
          {statusMessage.type === 'success' ? <CheckCircle2 size={16} /> : (statusMessage.type === 'error' ? <AlertCircle size={16} /> : <Zap size={16} />)}
          <span>{statusMessage.text}</span>
        </div>
      )}

      {/* ── Active Background Run Progress ── */}
      {activeRun && renderRunProgress(activeRun)}

      {/* ── Tab Switcher & Batch Actions Bar ── */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px', flexWrap: 'wrap', gap: '12px' }}>
        <div style={{ display: 'flex', gap: '8px' }}>
          <button
            onClick={() => setViewTab('drafts')}
            className={`btn ${viewTab === 'drafts' ? 'btn-primary' : 'btn-secondary'} btn-sm`}
          >
            <Pin size={14} />
            <span>Active Drafts ({bulkCandidates.length})</span>
          </button>

          <button
            onClick={() => setViewTab('scheduled')}
            className={`btn ${viewTab === 'scheduled' ? 'btn-primary' : 'btn-secondary'} btn-sm`}
          >
            <Clock size={14} />
            <span>Scheduled Queue ({pins.filter((p) => SCHEDULED_STATES.includes(p.status)).length})</span>
          </button>

          <button
            onClick={() => setViewTab('published')}
            className={`btn ${viewTab === 'published' ? 'btn-primary' : 'btn-secondary'} btn-sm`}
          >
            <CheckCircle2 size={14} />
            <span>Published Live ({pins.filter((p) => p.status === 'published').length})</span>
          </button>

          <button
            onClick={() => setBulkOpen(!bulkOpen)}
            className={`btn ${bulkOpen ? 'btn-primary' : 'btn-secondary'} btn-sm`}
            style={bulkOpen ? { background: 'linear-gradient(135deg, #e60023, #ff4757)', fontWeight: 800 } : undefined}
          >
            <CalendarClock size={14} />
            <span>Bulk Native Scheduler</span>
          </button>
        </div>

        {/* Global Batch Action Buttons */}
        {selectedPinIds.length > 0 && viewTab === 'drafts' && (
          <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
            <span style={{ fontSize: '0.82rem', fontWeight: 700, color: 'var(--text-primary)', marginRight: '4px' }}>
              🎯 {selectedPinIds.length} Selected:
            </span>

            <button
              onClick={handleSaveAllSelectedPins}
              disabled={savingEdit || loading}
              className="btn btn-secondary btn-sm"
              title="Save all title, description, board, and link edits"
            >
              <Check size={14} />
              <span>{savingEdit ? 'Saving...' : `Save Edits (${selectedPinIds.length})`}</span>
            </button>

            <button
              onClick={handleBatchPublishAll}
              disabled={loading || savingEdit}
              className="btn btn-primary btn-sm"
              style={{ background: 'linear-gradient(135deg, #e60023, #ff4757)', fontWeight: 800 }}
              title="Publish all selected pins sequentially in one browser run"
            >
              <Send size={14} />
              <span>🚀 Publish All ({selectedPinIds.length} Pins) at Once</span>
            </button>
          </div>
        )}
      </div>

      {/* ── Native Scheduler Collapsible ── */}
      {bulkOpen && (
        <div className="glass-card" style={{ padding: '20px', marginBottom: '20px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '8px' }}>
            <CalendarClock size={20} color="#e60023" />
            <h3 style={{ fontSize: '1.1rem', fontWeight: 800 }}>Pinterest Native Scheduled Batch</h3>
          </div>
          <p style={{ fontSize: '0.82rem', color: 'var(--text-secondary)', marginBottom: '14px' }}>
            Spaces out the {selectedPinIds.length} selected pins and sets Pinterest's "Publish at a later date" control.
          </p>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '12px', marginBottom: '14px' }}>
            <div className="form-group" style={{ marginBottom: 0 }}>
              <label className="form-label">Target Pinterest Account</label>
              <select
                className="form-input"
                value={selectedProfileId}
                onChange={(e) => setSelectedProfileId(e.target.value)}
              >
                {profiles.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name} {p.authenticated ? '🟢' : '🔴 (Not logged in)'}
                  </option>
                ))}
              </select>
            </div>

            <div className="form-group" style={{ marginBottom: 0 }}>
              <label className="form-label">Start Time</label>
              <input type="datetime-local" className="form-input" value={bulkStart} onChange={(e) => setBulkStart(e.target.value)} />
            </div>

            <div className="form-group" style={{ marginBottom: 0 }}>
              <label className="form-label">Spacing Interval</label>
              <select className="form-input" value={bulkSpacing} onChange={(e: any) => setBulkSpacing(e.target.value)}>
                <option value="interval">Every N Minutes</option>
                <option value="slots">Specific Daily Slots</option>
              </select>
            </div>

            {bulkSpacing === 'interval' ? (
              <div className="form-group" style={{ marginBottom: 0 }}>
                <label className="form-label">Interval (Minutes)</label>
                <input
                  type="number"
                  className="form-input"
                  min={15}
                  value={bulkInterval}
                  onChange={(e) => setBulkInterval(Math.max(15, Number(e.target.value)))}
                />
              </div>
            ) : (
              <div className="form-group" style={{ marginBottom: 0 }}>
                <label className="form-label">Daily Times (HH:MM)</label>
                <input
                  type="text"
                  className="form-input"
                  value={bulkSlots}
                  onChange={(e) => setBulkSlots(e.target.value)}
                  placeholder="09:00, 13:00, 18:00"
                />
              </div>
            )}
          </div>

          <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
            <button
              onClick={handleBulkPreview}
              disabled={bulkPlanning || selectedPinIds.length === 0}
              className="btn btn-secondary btn-sm"
            >
              <Eye size={14} />
              <span>{bulkPlanning ? 'Calculating...' : `Preview Schedule (${selectedPinIds.length} Pins)`}</span>
            </button>

            {bulkPreview && (
              <button
                onClick={handleBulkSchedule}
                disabled={bulkRunning}
                className="btn btn-primary btn-sm"
                style={{ background: 'linear-gradient(135deg, #e60023, #ff4757)', fontWeight: 800 }}
              >
                <Send size={14} />
                <span>{bulkRunning ? 'Scheduling via Chrome...' : `🚀 Start Batch Schedule (${bulkPreview.count} Pins)`}</span>
              </button>
            )}
          </div>

          {bulkError && (
            <div style={{ marginTop: '12px', color: '#f87171', fontSize: '0.82rem', fontWeight: 600 }}>
              ⚠️ {bulkError}
            </div>
          )}
        </div>
      )}

      {/* ── Main Two-Column View ── */}
      <div style={{ display: 'grid', gridTemplateColumns: '320px 1fr', gap: '24px', alignItems: 'start' }}>
        {/* ── 1. LEFT COLUMN: Pin Draft List / Selectors ── */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '0 4px' }}>
            <span style={{ fontSize: '0.82rem', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
              Pins ({filteredPins.length})
            </span>
            <div style={{ display: 'flex', gap: '6px' }}>
              <button
                onClick={handleSelectAllDrafts}
                className="btn btn-secondary btn-sm"
                style={{ fontSize: '0.72rem', padding: '3px 8px' }}
                title="Select all drafts"
              >
                Select All
              </button>
              <button
                onClick={handleClearSelection}
                className="btn btn-secondary btn-sm"
                style={{ fontSize: '0.72rem', padding: '3px 8px' }}
              >
                Clear
              </button>
            </div>
          </div>

          {filteredPins.length === 0 ? (
            <div className="glass-card" style={{ padding: '24px', textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.85rem' }}>
              No pins in this tab.
            </div>
          ) : (
            filteredPins.map((p) => {
              const isSelected = selectedPinIds.includes(p.id);
              const isActive = activePinId === p.id;
              const edits = getPinEdit(p);
              const targetProf = profiles.find((prof) => prof.id === (edits.profile_id || 'default'));

              return (
                <div
                  key={p.id}
                  onClick={() => {
                    setActivePinId(p.id);
                    if (!selectedPinIds.includes(p.id)) {
                      setSelectedPinIds([p.id]);
                    }
                  }}
                  className={`glass-card ${isActive ? 'glass-card-interactive' : ''}`}
                  style={{
                    padding: '12px',
                    cursor: 'pointer',
                    borderColor: isActive ? '#e60023' : (isSelected ? 'rgba(230,0,35,0.4)' : 'var(--border-subtle)'),
                    background: isSelected ? 'rgba(230, 0, 35, 0.08)' : 'var(--bg-card)',
                    display: 'flex',
                    gap: '12px',
                    alignItems: 'center',
                    transition: 'all 0.2s ease',
                  }}
                >
                  {/* Checkbox */}
                  <div
                    onClick={(e) => {
                      e.stopPropagation();
                      toggleSelectPin(p.id);
                    }}
                    style={{ cursor: 'pointer', display: 'flex', alignItems: 'center' }}
                  >
                    {isSelected ? (
                      <CheckSquare size={18} color="#e60023" />
                    ) : (
                      <Square size={18} color="var(--text-muted)" />
                    )}
                  </div>

                  {/* Thumbnail */}
                  <div style={{ width: '46px', height: '80px', borderRadius: '6px', overflow: 'hidden', background: '#000', flexShrink: 0 }}>
                    {p.image_path ? (
                      <img src={`/${p.image_path}`} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                    ) : (
                      <div style={{ width: '100%', height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '0.6rem', color: '#666' }}>9:16</div>
                    )}
                  </div>

                  {/* Info */}
                  <div style={{ flex: 1, overflow: 'hidden' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
                      {getStatusBadge(p.status)}
                      <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)', fontFamily: 'monospace' }}>
                        #{p.id.slice(0, 6)}
                      </span>
                    </div>
                    <h4 style={{ fontSize: '0.84rem', fontWeight: 700, margin: '0 0 4px', lineHeight: 1.3, color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {edits.title || 'Untitled Pin'}
                    </h4>
                    <div style={{ fontSize: '0.72rem', color: 'var(--text-secondary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      👤 {targetProf?.name || 'Default Account'} • 📌 {edits.board_name || 'No board'}
                    </div>
                  </div>
                </div>
              );
            })
          )}
        </div>

        {/* ── 2. RIGHT COLUMN: Multi-Pin Batch Editor & Inspector ── */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
          {/* ── BATCH APPLY TOOLBAR (When 2+ Pins Selected) ── */}
          {selectedPinIds.length > 1 && (
            <div className="glass-card" style={{ padding: '18px 20px', background: 'linear-gradient(135deg, rgba(230,0,35,0.06), rgba(99,102,241,0.06))', border: '1px solid rgba(230,0,35,0.3)' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px' }}>
                <Layers size={18} color="#e60023" />
                <strong style={{ fontSize: '0.95rem' }}>Batch Apply to All {selectedPinIds.length} Selected Variations</strong>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 1fr 1.2fr 1fr', gap: '10px' }}>
                {/* Bulk Account */}
                <div style={{ display: 'flex', gap: '6px' }}>
                  <select
                    className="form-input"
                    style={{ fontSize: '0.78rem', padding: '6px 8px' }}
                    value={bulkApplyProfile}
                    onChange={(e) => setBulkApplyProfile(e.target.value)}
                  >
                    {profiles.map((prof) => (
                      <option key={prof.id} value={prof.id}>
                        {prof.name} {prof.authenticated ? '🟢' : '🔴'}
                      </option>
                    ))}
                  </select>
                  <button onClick={handleBulkApplyProfile} className="btn btn-secondary btn-sm" style={{ whiteSpace: 'nowrap', fontSize: '0.74rem' }}>
                    Apply
                  </button>
                </div>

                {/* Bulk Board */}
                <div style={{ display: 'flex', gap: '6px' }}>
                  <input
                    type="text"
                    className="form-input"
                    style={{ fontSize: '0.8rem', padding: '6px 10px' }}
                    value={bulkApplyBoard}
                    onChange={(e) => setBulkApplyBoard(e.target.value)}
                    placeholder="Board Name"
                  />
                  <button onClick={handleBulkApplyBoard} className="btn btn-secondary btn-sm" style={{ whiteSpace: 'nowrap', fontSize: '0.74rem' }}>
                    Apply
                  </button>
                </div>

                {/* Bulk URL */}
                <div style={{ display: 'flex', gap: '6px' }}>
                  <input
                    type="url"
                    className="form-input"
                    style={{ fontSize: '0.8rem', padding: '6px 10px' }}
                    value={bulkApplyUrl}
                    onChange={(e) => setBulkApplyUrl(e.target.value)}
                    placeholder="Destination URL"
                  />
                  <button onClick={handleBulkApplyUrl} className="btn btn-secondary btn-sm" style={{ whiteSpace: 'nowrap', fontSize: '0.74rem' }}>
                    Apply
                  </button>
                </div>

                {/* Bulk Keywords */}
                <div style={{ display: 'flex', gap: '6px' }}>
                  <input
                    type="text"
                    className="form-input"
                    style={{ fontSize: '0.8rem', padding: '6px 10px' }}
                    value={bulkApplyKeywords}
                    onChange={(e) => setBulkApplyKeywords(e.target.value)}
                    placeholder="Tags (csv)"
                  />
                  <button onClick={handleBulkApplyKeywords} className="btn btn-secondary btn-sm" style={{ whiteSpace: 'nowrap', fontSize: '0.74rem' }}>
                    Apply
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* ── MULTI-PIN CARD INSPECTOR LIST (When 2+ Pins Selected) ── */}
          {selectedPinsList.length > 1 ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div style={{ fontSize: '0.9rem', fontWeight: 800, color: 'var(--text-primary)' }}>
                  Editing {selectedPinsList.length} Variations in Batch
                </div>
                <div style={{ display: 'flex', gap: '10px' }}>
                  <button
                    onClick={handleSaveAllSelectedPins}
                    disabled={savingEdit || loading}
                    className="btn btn-secondary btn-sm"
                  >
                    <Check size={14} />
                    <span>{savingEdit ? 'Saving All...' : 'Save All Changes'}</span>
                  </button>

                  <button
                    onClick={handleBatchPublishAll}
                    disabled={loading || savingEdit}
                    className="btn btn-primary btn-sm"
                    style={{ background: 'linear-gradient(135deg, #e60023, #ff4757)', fontWeight: 800 }}
                  >
                    <Send size={14} />
                    <span>🚀 Publish All {selectedPinsList.length} Pins</span>
                  </button>
                </div>
              </div>

              {selectedPinsList.map((p, idx) => {
                const edits = getPinEdit(p);
                return (
                  <div
                    key={p.id}
                    className="glass-card"
                    style={{
                      padding: '18px',
                      display: 'grid',
                      gridTemplateColumns: '120px 1fr auto',
                      gap: '18px',
                      alignItems: 'start',
                      border: '1px solid var(--border-subtle)',
                    }}
                  >
                    {/* 9:16 Thumbnail */}
                    <div style={{ aspectRatio: '9/16', borderRadius: '10px', overflow: 'hidden', background: '#000', position: 'relative' }}>
                      {p.image_path ? (
                        <img src={`/${p.image_path}`} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                      ) : (
                        <div style={{ width: '100%', height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '0.75rem' }}>9:16</div>
                      )}
                      <div style={{ position: 'absolute', top: '6px', left: '6px', background: 'rgba(0,0,0,0.7)', color: '#fff', fontSize: '0.68rem', fontWeight: 700, padding: '2px 6px', borderRadius: '4px' }}>
                        Var #{idx + 1}
                      </div>
                    </div>

                    {/* Editable Form for this pin */}
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                      <div>
                        <label className="form-label" style={{ fontSize: '0.75rem', marginBottom: '2px' }}>Pin Title</label>
                        <input
                          type="text"
                          className="form-input"
                          style={{ fontSize: '0.85rem', fontWeight: 600 }}
                          value={edits.title}
                          onChange={(e) => updatePinEdit(p.id, 'title', e.target.value)}
                          placeholder="Catchy Pinterest title..."
                        />
                      </div>

                      <div>
                        <label className="form-label" style={{ fontSize: '0.75rem', marginBottom: '2px' }}>Description</label>
                        <textarea
                          className="form-textarea"
                          rows={2}
                          style={{ fontSize: '0.8rem' }}
                          value={edits.description}
                          onChange={(e) => updatePinEdit(p.id, 'description', e.target.value)}
                          placeholder="Pin description with affiliate disclosures and tags..."
                        />
                      </div>

                      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '10px' }}>
                        <div>
                          <label className="form-label" style={{ fontSize: '0.75rem', marginBottom: '2px' }}>Account</label>
                          <select
                            className="form-input"
                            style={{ fontSize: '0.8rem' }}
                            value={edits.profile_id || 'default'}
                            onChange={(e) => {
                              updatePinEdit(p.id, 'profile_id', e.target.value);
                              loadBoardsForProfile(e.target.value);
                            }}
                          >
                            {profiles.map((prof) => (
                              <option key={prof.id} value={prof.id}>
                                {prof.name} {prof.authenticated ? '🟢' : '🔴'}
                              </option>
                            ))}
                          </select>
                        </div>

                        <div>
                          <label className="form-label" style={{ fontSize: '0.75rem', marginBottom: '2px' }}>Board</label>
                          <input
                            type="text"
                            list={`boards-list-${p.id}`}
                            className="form-input"
                            style={{ fontSize: '0.8rem' }}
                            value={edits.board_name}
                            onChange={(e) => updatePinEdit(p.id, 'board_name', e.target.value)}
                            placeholder="Board Name"
                          />
                          <datalist id={`boards-list-${p.id}`}>
                            {(accountBoards[edits.profile_id || 'default'] || []).map((b) => (
                              <option key={b} value={b} />
                            ))}
                          </datalist>
                        </div>

                        <div>
                          <label className="form-label" style={{ fontSize: '0.75rem', marginBottom: '2px' }}>Destination URL</label>
                          <input
                            type="url"
                            className="form-input"
                            style={{ fontSize: '0.8rem' }}
                            value={edits.destination_url}
                            onChange={(e) => updatePinEdit(p.id, 'destination_url', e.target.value)}
                            placeholder="https://..."
                          />
                        </div>
                      </div>
                    </div>

                    {/* Pin Actions */}
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', minWidth: '130px' }}>
                      {getStatusBadge(p.status)}

                      <button
                        onClick={() => handlePublishSinglePin(p.id)}
                        disabled={loading || p.status === 'published'}
                        className="btn btn-primary btn-sm"
                        style={{ fontSize: '0.78rem', background: 'linear-gradient(135deg, #e60023, #d0001f)', marginTop: '4px' }}
                        title="Publish this pin now"
                      >
                        <Send size={12} />
                        <span>Publish Now</span>
                      </button>

                      <button
                        onClick={() => {
                          setActivePinId(p.id);
                          setScheduleModalOpen(true);
                        }}
                        disabled={loading || p.status === 'published'}
                        className="btn btn-secondary btn-sm"
                        style={{ fontSize: '0.78rem' }}
                      >
                        <Calendar size={12} />
                        <span>Schedule</span>
                      </button>

                      {p.live_url && (
                        <a
                          href={p.live_url}
                          target="_blank"
                          rel="noreferrer"
                          style={{ fontSize: '0.74rem', color: '#34d399', textDecoration: 'none', display: 'flex', alignItems: 'center', gap: '3px', marginTop: '4px' }}
                        >
                          <span>Live Pin</span>
                          <ArrowUpRight size={11} />
                        </a>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          ) : (
            /* ── SINGLE PIN DETAILED INSPECTOR (When 1 Pin Selected) ── */
            activePin && activePinEdit && (
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 320px', gap: '24px' }}>
                {/* Detailed Editor Form */}
                <div className="glass-card" style={{ padding: '24px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '18px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <Pin size={20} color="#e60023" />
                      <h2 style={{ fontSize: '1.15rem', fontWeight: 800 }}>Pin SEO & Direct Publishing</h2>
                    </div>

                    <div style={{ display: 'flex', gap: '8px' }}>
                      <button
                        onClick={() => handlePublishSinglePin(activePin.id)}
                        disabled={loading || activePin.status === 'published'}
                        className="btn btn-primary btn-sm"
                        style={{ background: 'linear-gradient(135deg, #e60023, #d0001f)', fontWeight: 800 }}
                      >
                        <Send size={14} />
                        <span>🚀 Publish to Pinterest</span>
                      </button>

                      <button
                        onClick={() => setScheduleModalOpen(true)}
                        disabled={loading || activePin.status === 'published'}
                        className="btn btn-secondary btn-sm"
                      >
                        <Calendar size={14} />
                        <span>📅 Schedule</span>
                      </button>

                      <a
                        href={`/api/pins/${activePin.id}/export`}
                        download
                        className="btn btn-secondary btn-sm"
                        title="Export complete ZIP bundle"
                      >
                        <Download size={14} />
                      </a>
                    </div>
                  </div>

                  <div className="form-group">
                    <label className="form-label" style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span>Pinterest SEO Title</span>
                      <span style={{ fontSize: '0.75rem', color: activePinEdit.title.length > 60 ? '#f59e0b' : 'var(--text-muted)' }}>
                        {activePinEdit.title.length}/100 chars
                      </span>
                    </label>
                    <input
                      type="text"
                      className="form-input"
                      value={activePinEdit.title}
                      onChange={(e) => updatePinEdit(activePin.id, 'title', e.target.value)}
                      placeholder="Catchy, natural title..."
                    />
                  </div>

                  <div className="form-group">
                    <label className="form-label" style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span>Pin Description & Hook</span>
                      <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                        {activePinEdit.description.length}/500 chars
                      </span>
                    </label>
                    <textarea
                      className="form-textarea"
                      rows={3}
                      value={activePinEdit.description}
                      onChange={(e) => updatePinEdit(activePin.id, 'description', e.target.value)}
                      placeholder="Informative description with natural keywords and affiliate disclosure..."
                    />
                  </div>

                  <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 1fr 1fr', gap: '14px' }}>
                    <div className="form-group">
                      <label className="form-label">Target Pinterest Account</label>
                      <select
                        className="form-input"
                        value={activePinEdit.profile_id || 'default'}
                        onChange={(e) => {
                          updatePinEdit(activePin.id, 'profile_id', e.target.value);
                          loadBoardsForProfile(e.target.value);
                        }}
                      >
                        {profiles.map((prof) => (
                          <option key={prof.id} value={prof.id}>
                            {prof.name} {prof.authenticated ? '🟢' : '🔴 (Not logged in)'}
                          </option>
                        ))}
                      </select>
                    </div>

                    <div className="form-group">
                      <label className="form-label">Target Pinterest Board</label>
                      <input
                        type="text"
                        list={`boards-list-detail-${activePin.id}`}
                        className="form-input"
                        value={activePinEdit.board_name}
                        onChange={(e) => updatePinEdit(activePin.id, 'board_name', e.target.value)}
                        placeholder="e.g. Fall Style & Outfits"
                      />
                      <datalist id={`boards-list-detail-${activePin.id}`}>
                        {(accountBoards[activePinEdit.profile_id || 'default'] || []).map((b) => (
                          <option key={b} value={b} />
                        ))}
                      </datalist>
                    </div>

                    <div className="form-group">
                      <label className="form-label">Affiliate Destination URL</label>
                      <input
                        type="url"
                        className="form-input"
                        value={activePinEdit.destination_url}
                        onChange={(e) => updatePinEdit(activePin.id, 'destination_url', e.target.value)}
                        placeholder="https://..."
                      />
                    </div>
                  </div>

                  <div className="form-group">
                    <label className="form-label">Search Keywords & Tags (Comma-separated)</label>
                    <input
                      type="text"
                      className="form-input"
                      value={activePinEdit.keywords}
                      onChange={(e) => updatePinEdit(activePin.id, 'keywords', e.target.value)}
                      placeholder="pinterest finds, aesthetic, fall outfit"
                    />
                  </div>

                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '16px' }}>
                    <button
                      onClick={handleSaveAllSelectedPins}
                      disabled={savingEdit}
                      className="btn btn-secondary btn-sm"
                    >
                      <Check size={14} />
                      <span>{savingEdit ? 'Saving...' : 'Save Changes'}</span>
                    </button>

                    {activePin.live_url && (
                      <a
                        href={activePin.live_url}
                        target="_blank"
                        rel="noreferrer"
                        style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '0.82rem', color: '#34d399', textDecoration: 'none', fontWeight: 600 }}
                      >
                        <span>View Live Pin on Pinterest</span>
                        <ExternalLink size={14} />
                      </a>
                    )}
                  </div>

                  {/* Compliance Checklist */}
                  <div style={{
                    marginTop: '20px',
                    padding: '12px 16px',
                    background: 'rgba(16, 185, 129, 0.06)',
                    border: '1px solid rgba(16, 185, 129, 0.2)',
                    borderRadius: 'var(--radius-md)',
                  }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '6px' }}>
                      <ShieldCheck size={16} color="#34d399" />
                      <span style={{ fontSize: '0.82rem', fontWeight: 700, color: '#34d399' }}>
                        FTC & Pinterest Compliance Safeguards
                      </span>
                    </div>
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px', fontSize: '0.74rem', color: 'var(--text-secondary)' }}>
                      <div>✅ Affiliate commercial disclosure included</div>
                      <div>✅ AI transparency metadata embedded</div>
                      <div>✅ 100% matched to Product Truth</div>
                      <div>✅ Safe autonomous rate pacing</div>
                    </div>
                  </div>
                </div>

                {/* Live 9:16 Mockup */}
                <div>
                  <div style={{ fontSize: '0.82rem', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '10px' }}>
                    Live Pinterest Card Mockup
                  </div>
                  <div
                    className="glass-card"
                    style={{
                      padding: 0,
                      overflow: 'hidden',
                      borderRadius: '16px',
                      boxShadow: '0 12px 30px rgba(0,0,0,0.3)',
                      border: '1px solid rgba(255,255,255,0.1)',
                    }}
                  >
                    <div style={{ aspectRatio: '9/16', background: '#111', position: 'relative' }}>
                      {activePin.image_path ? (
                        <img src={`/${activePin.image_path}`} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                      ) : (
                        <div style={{ width: '100%', height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#555' }}>
                          No image
                        </div>
                      )}
                    </div>
                    <div style={{ padding: '14px' }}>
                      <h3 style={{ fontSize: '0.92rem', fontWeight: 700, margin: '0 0 6px', lineHeight: 1.3 }}>
                        {activePinEdit.title || 'Untitled Pin'}
                      </h3>
                      <p style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', margin: 0, lineHeight: 1.4, display: '-webkit-box', WebkitLineClamp: 3, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>
                        {activePinEdit.description || 'No description entered yet.'}
                      </p>
                    </div>
                  </div>
                </div>
              </div>
            )
          )}
        </div>
      </div>

      {/* ── Pinterest Accounts Manager Modal ── */}
      {accountsModalOpen && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(0, 0, 0, 0.75)',
            backdropFilter: 'blur(6px)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 1000,
            padding: '20px',
          }}
          onClick={() => setAccountsModalOpen(false)}
        >
          <div
            className="glass-card"
            style={{
              maxWidth: '680px',
              width: '100%',
              padding: '28px',
              background: '#18181b',
              border: '1px solid rgba(255, 255, 255, 0.15)',
              boxShadow: '0 20px 50px rgba(0, 0, 0, 0.6)',
              maxHeight: '90vh',
              overflowY: 'auto',
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <Pin size={24} color="#e60023" />
                <h2 style={{ fontSize: '1.25rem', fontWeight: 800, margin: 0 }}>Pinterest Accounts & Sessions</h2>
              </div>
              <button className="btn btn-secondary btn-sm" onClick={() => setAccountsModalOpen(false)}>
                ✕
              </button>
            </div>

            <p style={{ fontSize: '0.84rem', color: 'var(--text-secondary)', marginBottom: '20px', lineHeight: 1.5 }}>
              Connect 2-3+ separate Pinterest accounts. Log in once per account in Chrome; cookies stay saved permanently in isolated folders for automated publishing.
            </p>

            {/* List of Connected Profiles */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', marginBottom: '24px' }}>
              {profiles.map((prof) => (
                <div
                  key={prof.id}
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    padding: '14px 18px',
                    background: 'rgba(255, 255, 255, 0.03)',
                    border: `1px solid ${prof.authenticated ? 'rgba(16, 185, 129, 0.3)' : 'rgba(255, 255, 255, 0.08)'}`,
                    borderRadius: 'var(--radius-md)',
                    gap: '12px',
                  }}
                >
                  <div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px', flexWrap: 'wrap' }}>
                      <span style={{ fontWeight: 700, fontSize: '0.95rem' }}>{prof.name}</span>
                      {prof.is_default && (
                        <span style={{ fontSize: '0.7rem', padding: '2px 6px', background: 'rgba(59, 130, 246, 0.2)', color: '#60a5fa', borderRadius: '4px', fontWeight: 600 }}>
                          Default
                        </span>
                      )}
                      <span
                        style={{
                          fontSize: '0.72rem',
                          padding: '2px 8px',
                          borderRadius: '12px',
                          background: prof.authenticated ? 'rgba(16, 185, 129, 0.15)' : 'rgba(239, 68, 68, 0.15)',
                          color: prof.authenticated ? '#34d399' : '#f87171',
                          fontWeight: 600,
                        }}
                      >
                        {prof.authenticated ? '🟢 Active Session' : '🔴 Not Authenticated'}
                      </span>
                    </div>
                    <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                      ID: <code>{prof.id}</code> • {(accountBoards[prof.id] || []).length || prof.cached_boards_count || 0} boards cached
                    </div>
                  </div>

                  <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                    <button
                      onClick={() => handleLaunchProfileLogin(prof.id)}
                      className="btn btn-secondary btn-sm"
                      style={{ fontSize: '0.78rem' }}
                      title="Open Chrome to log into this account"
                    >
                      <Zap size={13} />
                      <span>{prof.authenticated ? 'Re-login' : '🔑 Log In'}</span>
                    </button>

                    <button
                      onClick={() => handleRefreshBoardsForProfile(prof.id)}
                      disabled={refreshingBoardsFor === prof.id}
                      className="btn btn-secondary btn-sm"
                      style={{ fontSize: '0.78rem' }}
                      title="Fetch live boards dropdown from Pinterest"
                    >
                      <RefreshCw size={13} className={refreshingBoardsFor === prof.id ? 'spin' : ''} />
                      <span>Boards</span>
                    </button>

                    {!prof.is_default && (
                      <button
                        onClick={() => handleDeleteProfile(prof.id)}
                        className="btn btn-secondary btn-sm"
                        style={{ fontSize: '0.78rem', color: '#f87171' }}
                        title="Delete this profile"
                      >
                        <Trash2 size={13} />
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>

            {/* Add New Profile Section */}
            <div
              style={{
                padding: '16px 20px',
                background: 'rgba(255, 255, 255, 0.02)',
                border: '1px dashed rgba(255, 255, 255, 0.15)',
                borderRadius: 'var(--radius-md)',
              }}
            >
              <h4 style={{ fontSize: '0.9rem', fontWeight: 700, margin: '0 0 10px' }}>➕ Add Another Pinterest Profile</h4>
              <div style={{ display: 'flex', gap: '10px' }}>
                <input
                  type="text"
                  className="form-input"
                  placeholder="Account Name (e.g. Fashion Finds, Home Aesthetic)"
                  value={newProfileName}
                  onChange={(e) => setNewProfileName(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') handleCreateProfile();
                  }}
                  style={{ flex: 1 }}
                />
                <button
                  onClick={handleCreateProfile}
                  disabled={creatingProfile || !newProfileName.trim()}
                  className="btn btn-primary btn-sm"
                  style={{ background: 'linear-gradient(135deg, #e60023, #d0001f)', fontWeight: 700, whiteSpace: 'nowrap' }}
                >
                  <Plus size={14} />
                  <span>{creatingProfile ? 'Creating...' : 'Create & Connect'}</span>
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── Single Pin Schedule Modal ── */}
      {scheduleModalOpen && activePin && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(0,0,0,0.7)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 1000,
            padding: '20px',
          }}
          onClick={() => setScheduleModalOpen(false)}
        >
          <div
            className="glass-card"
            style={{ maxWidth: '440px', width: '100%', padding: '24px', background: '#1c1c20' }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
              <h3 style={{ fontSize: '1.1rem', fontWeight: 800, margin: 0 }}>📅 Schedule Pin Publication</h3>
              <button className="btn btn-secondary btn-sm" onClick={() => setScheduleModalOpen(false)}>✕</button>
            </div>
            <div className="form-group">
              <label className="form-label">Publication Date & Time</label>
              <input
                type="datetime-local"
                className="form-input"
                value={scheduleDate}
                onChange={(e) => setScheduleDate(e.target.value)}
              />
            </div>
            <button
              onClick={async () => {
                try {
                  await api.schedulePin(activePin.id, scheduleDate);
                  showStatus('📅 Pin scheduled successfully!', 'success');
                  setScheduleModalOpen(false);
                  await loadPins();
                } catch (e: any) {
                  showStatus(`Scheduling failed: ${e.message}`, 'error');
                }
              }}
              className="btn btn-primary btn-sm"
              style={{ width: '100%', background: 'linear-gradient(135deg, #e60023, #d0001f)' }}
            >
              Confirm Schedule
            </button>
          </div>
        </div>
      )}
    </div>
  );
};
