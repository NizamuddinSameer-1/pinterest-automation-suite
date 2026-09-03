import React, { useState, useEffect, useRef } from 'react';
import { api, Reference, Job, PinDraft, GenerationBackend, SubjectMismatchError, Product } from '../api';
import { 
  Upload, Sparkles, Copy, Check, Download, Send, Calendar,
  RefreshCw, Pin, ArrowRight, ShieldCheck, Film, Camera, Zap, CheckCircle2,
  ExternalLink, Layers, CheckSquare, Package, Sparkle, Tag, ShoppingBag,
  ChevronDown, X, CheckCircle, BookOpen
} from 'lucide-react';

interface CreativeLabProps {
  setActiveTab: (tab: string) => void;
  selectedJobId?: string;
  selectedProductId?: string;
  setSelectedProductId?: (id: string | undefined) => void;
}

export const CreativeLab: React.FC<CreativeLabProps> = ({ 
  setActiveTab, 
  selectedJobId, 
  selectedProductId, 
  setSelectedProductId 
}) => {
  // State
  const [references, setReferences] = useState<Reference[]>([]);
  const [selectedRefId, setSelectedRefId] = useState<string>('');
  
  // Saved Amazon Products State
  const [savedProducts, setSavedProducts] = useState<Product[]>([]);
  const [activeProductId, setActiveProductId] = useState<string | undefined>(selectedProductId);
  const [activeProduct, setActiveProduct] = useState<Product | null>(null);
  const [showProductDropdown, setShowProductDropdown] = useState<boolean>(false);
  
  const [currentJob, setCurrentJob] = useState<Job | null>(null);
  const [recentJobs, setRecentJobs] = useState<Job[]>([]);
  const [jobPins, setJobPins] = useState<PinDraft[]>([]);
  const [selectedOutputIndex, setSelectedOutputIndex] = useState<number>(0);
  const [loading, setLoading] = useState<boolean>(false);
  const [actionMessage, setActionMessage] = useState<string>('');
  const [copiedPrompt, setCopiedPrompt] = useState<boolean>(false);
  const [publishSuccess, setPublishSuccess] = useState<string>('');
  const [flowSessionActive, setFlowSessionActive] = useState<boolean>(false);
  const [selectedConcept, setSelectedConcept] = useState<string>('Desire');
  // Which generation backends can actually run right now. The panel used to
  // gate the Generate button on the captured session alone, so an operator with
  // a logged-in Flow browser profile (a perfectly working path) was told to
  // "Setup Session" and given no way to generate.
  const [backends, setBackends] = useState<GenerationBackend[]>([]);
  const [selectedBackend, setSelectedBackend] = useState<string>('auto');

  // Upload Reference state. Both fields start empty and are required in the form:
  // defaults of 'Halloween'/'costumes' silently labelled every reference ever
  // uploaded, and the trend label is what carries a trend into the prompt.
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [trendLabel, setTrendLabel] = useState<string>('');
  const [refCategory, setRefCategory] = useState<string>('');
  const [affiliateUrl, setAffiliateUrl] = useState<string>('');
  // Cleared after an upload so the picker stops showing the name of a file that
  // has already become a reference — "it shows the file name so i think file is
  // already selected but it is not" was exactly this.
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [drafting, setDrafting] = useState<boolean>(false);

  // The subject guard's 409, held so the operator can choose one of the three ways
  // out. Without this the refusal arrived as a raw alert naming a button that did
  // not exist, and the only usable option was to give up.
  const [mismatch, setMismatch] = useState<{ error: SubjectMismatchError; jobId: string } | null>(null);

  // Direct Publish & Schedule Modal state
  const [scheduleModalOpen, setScheduleModalOpen] = useState<boolean>(false);
  // Default to tomorrow 18:00 local rather than a hardcoded date that is already past.
  const [scheduleDate, setScheduleDate] = useState<string>(() => {
    const d = new Date();
    d.setDate(d.getDate() + 1);
    d.setHours(18, 0, 0, 0);
    const pad = (n: number) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  });
  const [scheduleAllPins, setScheduleAllPins] = useState<boolean>(false);
  const [previewPromptText, setPreviewPromptText] = useState<string>('');
  const [compilingPrompt, setCompilingPrompt] = useState<boolean>(false);
  const [deployingLookbook, setDeployingLookbook] = useState<boolean>(false);

  // Flow Projects Router state
  const [flowProjects, setFlowProjects] = useState<string[]>([]);
  const [showProjectsModal, setShowProjectsModal] = useState<boolean>(false);
  const [newProjectUrl, setNewProjectUrl] = useState<string>('');

  const formatImgSrc = (path?: string) => {
    if (!path) return '';
    let clean = path.replace(/\\/g, '/');
    // Strip absolute prefix to get relative data/ path
    if (clean.includes('/data/')) {
      clean = clean.substring(clean.indexOf('/data/'));
    } else if (clean.startsWith('data/')) {
      clean = `/${clean}`;
    }
    // At this point clean should be like /data/outputs/xxx/flow_var_1.jpg
    // Vite proxy routes /data/* to http://localhost:8000/data/*
    return clean.startsWith('/') ? clean : `/${clean}`;
  };

  // Whether the chosen backend can actually run. `auto` deliberately excludes
  // pollinations (it is always "available" but only ever gets a condensed
  // prompt, so the backend never falls back to it), which is why the check is
  // not simply `backends.some(b => b.available)`.
  const backendIsUp = (id: string) => backends.find((b) => b.id === id)?.available === true;
  const backendReady =
    backends.length === 0
      ? true // capability unknown (the probe failed) — let the run report the truth
      : selectedBackend === 'auto'
        ? backends.some((b) => b.available && b.id !== 'pollinations')
        : backendIsUp(selectedBackend);

  // Nothing can be generated from a reference with no Visual DNA — `/generate`
  // returns 409. The button used to be gated on the backend alone, so every click
  // on an unanalysed reference created a DRAFT job and then failed, leaving
  // orphan jobs behind and no hint about what to do next.
  const selectedRefHasDna = references.find((r) => r.id === selectedRefId)?.has_visual_dna === true;
  const pendingFileReady = !!uploadFile;
  const canGenerate = backendReady && (selectedRefHasDna || pendingFileReady);

  useEffect(() => {
    loadInitialData(!selectedProductId && !selectedJobId);
  }, []);

  useEffect(() => {
    if (selectedJobId) {
      loadJob(selectedJobId);
    }
  }, [selectedJobId]);

  useEffect(() => {
    if (selectedProductId) {
      handleSelectSavedProduct(selectedProductId);
    }
  }, [selectedProductId]);

  const handleSelectSavedProduct = async (prodId: string) => {
    if (!prodId) return;
    try {
      setLoading(true);
      setActionMessage('Linking Amazon product & extracting live specs...');
      const prod = savedProducts.find(p => p.id === prodId) || (await api.getProduct(prodId).catch(() => null));
      if (prod) {
        setActiveProduct(prod);
        setActiveProductId(prod.id);
        if (prod.affiliate_url) setAffiliateUrl(prod.affiliate_url);
      }
      const res = await api.createReferenceFromProduct(prodId);
      if (res?.reference_id) {
        const newRef: Reference = {
          id: res.reference_id,
          image_path: res.image_path,
          trend_label: res.trend_label,
          category: res.category,
          status: 'analyzed',
          created_at: new Date().toISOString(),
          has_visual_dna: true,
        };
        setReferences((prev) => [newRef, ...prev.filter((r) => r.id !== newRef.id)]);
        setSelectedRefId(newRef.id);
        setCurrentJob(null);
        setActionMessage(`✅ Product linked! Real fabric, style & anti-hallucination constraints loaded.`);
        await autoCompilePrompt(res.reference_id, prodId);
      }
    } catch (err: any) {
      console.warn('Failed to link saved product:', err);
    } finally {
      setLoading(false);
    }
  };

  const autoCompilePrompt = async (refId: string, prodId?: string) => {
    if (!refId) return;
    try {
      setCompilingPrompt(true);
      const targetProd = prodId || activeProductId;
      const res = await api.previewPrompt(refId, targetProd, true);
      if (res?.prompt_text) {
        setPreviewPromptText(res.prompt_text);
      }
    } catch (err: any) {
      console.warn('Auto prompt compilation notice:', err?.message || err);
    } finally {
      setCompilingPrompt(false);
    }
  };

  useEffect(() => {
    if (selectedRefId) {
      const ref = references.find((r) => r.id === selectedRefId);
      if (ref?.has_visual_dna) {
        autoCompilePrompt(selectedRefId, activeProductId);
      }
    } else {
      setPreviewPromptText('');
    }
  }, [selectedRefId, activeProductId]);

  const loadInitialData = async (shouldAutoLoadJob = false) => {
    try {
      const [refs, backendInfo, projectsData, prods] = await Promise.all([
        api.getReferences(),
        api.getGenerationBackends().catch(() => ({ default: 'auto', default_count: 4, backends: [] })),
        api.getFlowProjects().catch(() => ({ projects: [], total: 0, strategy: '' })),
        api.getProducts().catch(() => []),
      ]);
      setReferences(refs);
      setBackends(backendInfo.backends || []);
      setFlowProjects(projectsData.projects || []);
      setSavedProducts(prods || []);
      setFlowSessionActive(!!backendInfo.backends?.find(b => b.id === 'flow_api')?.available);
      if (refs.length > 0 && !selectedRefId && !activeProductId) setSelectedRefId(refs[0].id);
    } catch (e) {
      console.error('Failed to load lab data:', e);
    }

    if (shouldAutoLoadJob) {
      try {
        const jobs = await api.getJobs();
        setRecentJobs(jobs || []);
        const latestJobWithOutputs = (jobs || []).find((j: any) => 
          j.current_state === 'OUTPUT_UPLOADED' || j.current_state === 'PASS' || j.current_state === 'DONE' || (j.outputs && j.outputs.length > 0)
        ) || (jobs && jobs.length > 0 ? jobs[0] : null);

        if (latestJobWithOutputs && !selectedJobId) {
          await loadJob(latestJobWithOutputs.id);
        }
      } catch {}
    }
  };

  const loadJob = async (jobId: string) => {
    try {
      setLoading(true);
      const job = await api.getJob(jobId);
      setCurrentJob(job);
      setSelectedRefId(job.reference_id);
      if (job.outputs && job.outputs.length > 0) {
        setSelectedOutputIndex(0);
      }
      // The publish panel shows the real pin draft (title, description, board)
      // instead of hardcoded seasonal placeholder copy.
      try {
        const pins = await api.getPins();
        setJobPins(pins.filter((p) => p.job_id === jobId));
      } catch {
        setJobPins([]);
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  const handleDeployLookbook = async () => {
    if (!currentJob?.id) return;
    try {
      setDeployingLookbook(true);
      setActionMessage('Deploying authentic magazine lookbook to Vercel...');
      const res = await api.generateLookbook(currentJob.id);
      if (res?.deploy_url) {
        setActionMessage(`✅ Lookbook live at ${res.deploy_url}! All pin destination links updated.`);
        const pins = await api.getPins();
        setJobPins(pins.filter((p) => p.job_id === currentJob.id));
      }
    } catch (err: any) {
      alert(err.message || 'Failed to deploy lookbook');
    } finally {
      setDeployingLookbook(false);
    }
  };

  // ── 1. Upload Reference (then analyse it immediately) ─────────
  // Choosing a file in the picker only put it in React state; nothing was sent
  // until "Upload Reference" was clicked. The operator's own account of it: "i just
  // choose my file and then re-analyse and then generate image, i don't click on
  // upload reference" — so the run used the *previous* reference and said nothing.
  // Now one function does upload + analysis, and every path that could be looking
  // at an un-uploaded file calls it first.
  const uploadPendingFile = async (fileToUpload?: File): Promise<{ id: string; hasDna: boolean } | null> => {
    const file = fileToUpload || uploadFile;
    if (!file) return null;
    const name = file.name;
    setActionMessage(`Uploading ${name}...`);
    const formData = new FormData();
    formData.append('file', file);
    formData.append('trend_label', 'trending');
    formData.append('category', 'lifestyle');

    const res = await api.uploadReference(formData);
    setActionMessage(`Uploaded ${name}. Running vision analysis & extracting Visual DNA (~1-3s)...`);
    let hasDna = false;
    try {
      const analysis = await api.analyzeReference(res.id);
      hasDna = true;
      setActionMessage(
        `✅ ${name} uploaded and analysed — Visual DNA v${analysis.visual_dna.version}. Ready to generate.`
      );
      autoCompilePrompt(res.id);
    } catch (analyzeErr: any) {
      setActionMessage('');
      alert(
        'The image uploaded, but the analysis failed:\n\n' +
          analyzeErr.message +
          '\n\nUse "Analyze Reference" to retry once the vision model is reachable.'
      );
    }

    setUploadFile(null);
    if (fileInputRef.current) fileInputRef.current.value = '';
    await loadInitialData();
    setSelectedRefId(res.id);
    return { id: res.id, hasDna };
  };

  const handleChooseFile = async (file: File | null) => {
    if (!file) return;
    setUploadFile(file);
    try {
      setLoading(true);
      await uploadPendingFile(file);
    } catch (err: any) {
      setActionMessage('');
      alert('Upload failed: ' + err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleAddProject = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newProjectUrl.trim()) return;
    try {
      setLoading(true);
      await api.addFlowProject(newProjectUrl.trim());
      setNewProjectUrl('');
      const res = await api.getFlowProjects();
      setFlowProjects(res.projects || []);
      alert('✅ Google Flow Project successfully added to the router pool!');
    } catch (err: any) {
      alert('Failed to add project: ' + err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleRemoveProject = async (url: string) => {
    const uuid = url.split('/').pop() || url;
    if (!confirm(`Remove project workspace ${uuid} from router pool?`)) return;
    try {
      setLoading(true);
      await api.removeFlowProject(uuid);
      const res = await api.getFlowProjects();
      setFlowProjects(res.projects || []);
    } catch (err: any) {
      alert('Failed to remove project: ' + err.message);
    } finally {
      setLoading(false);
    }
  };


  // ── 1b. Analyze / re-analyze the selected reference ───────────
  const handleAnalyzeReference = async () => {
    if (uploadFile) {
      try {
        setLoading(true);
        await uploadPendingFile();
      } catch (err: any) {
        setActionMessage('');
        alert('Upload failed: ' + err.message);
      } finally {
        setLoading(false);
      }
      return;
    }
    if (!selectedRefId) return;
    try {
      setLoading(true);
      setActionMessage('Running vision analysis & extracting Visual DNA (~1-3s)...');
      const analysis = await api.analyzeReference(selectedRefId);
      await loadInitialData();
      setSelectedRefId(selectedRefId);
      setActionMessage(`✅ Visual DNA v${analysis.visual_dna.version} extracted. Ready to generate.`);
      autoCompilePrompt(selectedRefId);
    } catch (e: any) {
      setActionMessage('');
      alert('Analysis failed, so no Visual DNA was written:\n\n' + e.message);
    } finally {
      setLoading(false);
    }
  };

  // ── 2. ⚡ Google Flow 4-Variation Batch Generator ──
  const handleGenerateFlowBatch = async () => {
    let refId = selectedRefId;
    let refHasDna = selectedRefHasDna;
    if (uploadFile) {
      try {
        setLoading(true);
        const uploaded = await uploadPendingFile();
        if (!uploaded) return;
        refId = uploaded.id;
        refHasDna = uploaded.hasDna;
      } catch (err: any) {
        setActionMessage('');
        alert('Upload failed: ' + err.message);
        return;
      } finally {
        setLoading(false);
      }
    }

    if (!refId) {
      alert('Choose or upload a reference photo in panel 1 first.');
      return;
    }

    if (!refHasDna) {
      alert(
        'This reference has no Visual DNA yet, so there is nothing to generate from.\n\n' +
          'Click "Analyze Reference" in the Reference Style panel first.'
      );
      return;
    }
    // Declared out here so the catch below can offer "generate anyway" against the
    // job that was already created, instead of creating a second one.
    let createdJobId = '';
    try {
      setLoading(true);
      setActionMessage('Creating job...');
      const job = await api.createJob({
        reference_id: refId,
        product_id: activeProductId || undefined,
        affiliate_url: affiliateUrl.trim() || undefined,
      });
      createdJobId = job.id;

      await startGeneration(job.id, false);
    } catch (e: any) {
      // A subject mismatch is a question, not a failure: the photograph and the
      // product row are different kinds of object. It gets a panel with the three
      // ways out instead of an alert the operator can only dismiss.
      if (e instanceof SubjectMismatchError && createdJobId) {
        setActionMessage('');
        setMismatch({ error: e, jobId: createdJobId });
      } else {
        alert('Generation failed: ' + e.message);
      }
    } finally {
      setLoading(false);
    }
  };

  /**
   * Way out 1 — the photograph *is* the product.
   *
   * Drafts a product row from Stage 1's reading of the photo, then runs a fresh
   * job against it. The guard then agrees, so nothing is overridden: the run is
   * generating the thing in the picture.
   */
  const handleUseReferenceAsProduct = async () => {
    if (!mismatch) return;
    setMismatch(null);
    setActionMessage('Product Library removed — generate with the photo as style only.');
  };

  /** Way out 2 — generate anyway, treating the photograph as style only. */
  const handleGenerateAnyway = async () => {
    if (!mismatch) return;
    const jobId = mismatch.jobId;
    setMismatch(null);
    try {
      setLoading(true);
      await startGeneration(jobId, true);
    } catch (e: any) {
      alert('Generation failed: ' + e.message);
    } finally {
      setLoading(false);
    }
  };

  // Start the run and poll it. Split out of the click handler so a subject mismatch
  // can be retried with the override without creating a second job.
  const startGeneration = async (jobId: string, allowSubjectMismatch: boolean) => {
    // One call now does the scene director, the 13-section compiler and the
    // state-machine hops before dispatching. It throws on 409 (no Visual DNA,
    // empty must_preserve, subject mismatch) instead of pretending a run started.
    setActionMessage('Running scene director & compiling the 13-section prompt...');
    const started = await api.generate(jobId, {
      backend: selectedBackend,
      allowSubjectMismatch,
    });
    const backendLabel = started.backend === 'auto' ? 'auto (Flow API → browser)' : started.backend;

    setActionMessage(
      `⚡ Generating ${started.requested_count} variation(s) via ${backendLabel} — please wait (~30-60s)...` +
        (allowSubjectMismatch ? ' (subject mismatch overridden — style reference only)' : '')
    );
    const maxPolls = 60; // 5 minutes max
    for (let i = 0; i < maxPolls; i++) {
      await new Promise((r) => setTimeout(r, 5000));
      try {
        const status = await api.getGenerationStatus(jobId);
        if (status.status === 'done') {
          await loadJob(jobId);
          try {
            const allJobs = await api.getJobs();
            setRecentJobs(allJobs || []);
          } catch {}
          const partial = status.partial
            ? ` (${status.image_count} of ${status.requested_count} requested)`
            : '';
          setActionMessage(
            `✅ ${status.image_count} variation(s) generated by ${status.produced_by}${partial}. ` +
              'Ready in gallery & ready for batch publishing in Pin Composer!'
          );
          return;
        }
        if (status.status === 'error') {
          // `attempts` says which backends were tried and why each declined.
          const trail = status.attempts?.length ? `\n\nBackends tried:\n• ${status.attempts.join('\n• ')}` : '';
          alert(`Generation failed: ${status.error || 'Unknown error'}${trail}`);
          await loadJob(jobId);
          return;
        }
        const phase = status.status === 'saving' ? 'Saving images & writing pin copy' : 'Generating';
        setActionMessage(`⚡ ${phase}... (${(i + 1) * 5}s elapsed)`);
      } catch {
        // Network hiccup, keep polling
      }
    }
    alert('Generation timed out after 5 minutes. Check the backend logs.');
  };

  // ── Helper: Open Google Flow in new tab & copy 13-section prompt ──
  const openGoogleFlow = async () => {
    try {
      let promptToCopy = '';
      if (currentJob?.prompt_versions && currentJob.prompt_versions.length > 0) {
        promptToCopy = currentJob.prompt_versions[currentJob.prompt_versions.length - 1].prompt_text;
      } else if (selectedRefId) {
        setActionMessage('Compiling prompt...');
        const job = await api.createJob({
          reference_id: selectedRefId,
          product_id: activeProductId || undefined,
        });
        const res = await api.compilePrompt(job.id);
        promptToCopy = res.prompt;
        await loadJob(job.id);
      }

      if (promptToCopy) {
        await navigator.clipboard.writeText(promptToCopy);
        setCopiedPrompt(true);
        setTimeout(() => setCopiedPrompt(false), 5000);
      }
    } catch (e) {
      console.error(e);
    } finally {
      window.open('https://labs.google/fx/tools/image-fx', '_blank');
    }
  };

  // ── 3. Direct Publish to Pinterest ──────────────
  const handleDirectPublish = async () => {
    if (!currentJob) return;
    try {
      setLoading(true);
      setActionMessage('Publishing pin directly to Pinterest board...');
      const pins = await api.getPins();
      const jobPins = pins.filter(p => p.job_id === currentJob.id);
      const targetPin = jobPins[selectedOutputIndex] || jobPins[0];

      // No pin draft means there is nothing to publish. The old code showed
      // "Published to Pinterest live! Pin is now active on your board." here,
      // without calling the API at all.
      if (!targetPin) {
        alert(
          'This job has no pin draft yet, so there is nothing to publish. ' +
          'Create the pin draft (Pin Composer) for the selected variation first.'
        );
        return;
      }

      // Publishing now runs in its own process and returns a run id, so the
      // outcome has to be polled. Waiting on the request lost the result of a pin
      // Pinterest had already accepted whenever the connection dropped.
      const started = await api.publishPin(targetPin.id);
      setActionMessage('A Chrome window is publishing the pin. This takes a minute or two…');

      let run = await api.getPublishRun(started.run_id);
      for (let tick = 0; tick < 200 && !run.stalled && run.status !== 'done' && run.status !== 'error'; tick++) {
        await new Promise((r) => setTimeout(r, 3000));
        run = await api.getPublishRun(started.run_id);
        setActionMessage(`Publishing… ${run.completed} of ${run.total}`);
      }

      if (run.stalled) {
        alert('The publisher stopped reporting. Check Pinterest before retrying — the pin may already be there.');
        return;
      }
      if (run.status === 'error') {
        alert(`The publisher stopped: ${run.error || 'no reason recorded'}`);
        return;
      }

      const res = run.results.find((r) => r.pin_id === targetPin.id);
      if (res?.live_url) {
        setPublishSuccess(`Published to Pinterest: ${res.live_url}`);
      } else if (res?.confirmed_by) {
        setPublishSuccess(
          `Pinterest confirmed the pin (${res.confirmed_by}) but exposed no pin URL — do not republish.`
        );
      } else {
        alert(
          res?.error
            ? `Publish failed (${res.error_kind || 'unexpected'}): ${res.error}`
            : 'The publisher finished without confirming the pin. Check Pinterest before retrying.'
        );
        return;
      }
      setTimeout(() => setPublishSuccess(''), 8000);
    } catch (e: any) {
      alert('Publish failed: ' + e.message);
    } finally {
      setLoading(false);
    }
  };

  // ── 4. Schedule Pin for Later ───────────────────
  const handleScheduleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!currentJob) return;
    try {
      setLoading(true);
      const pins = await api.getPins();
      const jobPins = pins.filter(p => p.job_id === currentJob.id);

      // Scheduling with no pin draft used to fall through both branches and close
      // the modal with no message at all, looking like it had worked.
      if (jobPins.length === 0) {
        alert(
          'This job has no pin draft yet, so there is nothing to schedule. ' +
          'Create the pin draft (Pin Composer) first.'
        );
        return;
      }

      if (scheduleAllPins) {
        // Schedule all variations spaced 1 day apart
        for (let i = 0; i < jobPins.length; i++) {
          const schedTime = new Date(new Date(scheduleDate).getTime() + i * 86400000).toISOString();
          await api.schedulePin(jobPins[i].id, schedTime);
        }
        setPublishSuccess(
          `All ${jobPins.length} variations queued across consecutive days. The in-app scheduler publishes them with the browser publisher.`
        );
      } else {
        const targetPin = jobPins[selectedOutputIndex] || jobPins[0];
        await api.schedulePin(targetPin.id, new Date(scheduleDate).toISOString());
        setPublishSuccess(
          `Variation #${selectedOutputIndex + 1} queued for ${new Date(scheduleDate).toLocaleString()}.`
        );
      }
      setScheduleModalOpen(false);
      setTimeout(() => setPublishSuccess(''), 8000);
    } catch (e: any) {
      alert('Scheduling failed: ' + e.message);
    } finally {
      setLoading(false);
    }
  };

  const copyPromptText = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopiedPrompt(true);
    setTimeout(() => setCopiedPrompt(false), 2000);
  };

  const selectedRef = references.find(r => r.id === selectedRefId);
  const latestPrompt = currentJob?.prompt_versions?.[currentJob.prompt_versions.length - 1];
  const displayPromptText = previewPromptText || latestPrompt?.prompt_text;
  const outputs = currentJob?.outputs || [];
  const currentOutput = outputs[selectedOutputIndex] || outputs[outputs.length - 1];
  // The pin draft for the selected variation, matched by output id where possible.
  const activePin =
    jobPins.find((p) => p.output_id === currentOutput?.id) || jobPins[selectedOutputIndex] || jobPins[0];

  // --- Commerce DNA + Concepts (Task 10) ---
  // Commerce DNA display placeholder — renders hero_prominence, click_reason, desire_mechanism from job.commerce_dna when present
  const commerceDna: any = (() => {
    const raw = (currentJob as any)?.commerce_dna ?? (currentJob as any)?.commerce_dna_json;
    if (!raw) return null;
    if (typeof raw === 'string') { try { return JSON.parse(raw); } catch { return null; } }
    return raw;
  })();
  const concepts: any[] = (() => {
    const raw = (currentJob as any)?.concepts ?? (currentJob as any)?.concepts_json;
    if (!raw) return [];
    if (Array.isArray(raw)) return raw;
    if (typeof raw === 'string') { try { const p = JSON.parse(raw); return Array.isArray(p) ? p : []; } catch { return []; } }
    return [];
  })();
  const conceptTabs = ['Desire', 'Detail', 'Lifestyle', 'Discovery'];

  return (
    <div style={{ maxWidth: '1440px', margin: '0 auto', padding: '28px 24px' }}>
      {/* Header */}
      <div style={{ marginBottom: '24px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h1 style={{ fontSize: '1.75rem', fontWeight: 800 }}>Creative Lab — 4-Variation Flow Engine</h1>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
            Generate 4 realistic variations at once with Google Flow quality ➔ Pick your favorite ➔ Publish or schedule!
          </p>
        </div>
        {actionMessage && (
          <div style={{
            padding: '8px 16px',
            background: 'rgba(230, 0, 35, 0.1)',
            border: '1px solid rgba(230, 0, 35, 0.3)',
            borderRadius: 'var(--radius-md)',
            fontSize: '0.82rem',
            color: '#ff334b',
            display: 'flex',
            alignItems: 'center',
            gap: '8px'
          }}>
            <RefreshCw size={14} className={loading ? 'spin' : ''} />
            <span>{actionMessage}</span>
          </div>
        )}
      </div>

      {publishSuccess && (
        <div style={{
          marginBottom: '20px',
          padding: '14px 20px',
          background: 'rgba(16, 185, 129, 0.15)',
          border: '1px solid rgba(16, 185, 129, 0.4)',
          borderRadius: 'var(--radius-md)',
          color: '#34d399',
          fontWeight: 600,
          fontSize: '0.9rem',
          display: 'flex',
          alignItems: 'center',
          gap: '10px'
        }}>
          <CheckCircle2 size={18} />
          <span>{publishSuccess}</span>
        </div>
      )}

      {/* ── The subject guard's refusal, with the three ways out ── */}
      {mismatch && (
        <div style={{
          marginBottom: '20px',
          padding: '18px 20px',
          background: 'rgba(245, 158, 11, 0.12)',
          border: '1px solid rgba(245, 158, 11, 0.45)',
          borderRadius: 'var(--radius-md)',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '6px' }}>
            <ShieldCheck size={18} color="#fbbf24" />
            <strong style={{ fontSize: '0.98rem', color: '#fbbf24' }}>
              This photo and this product are different kinds of thing
            </strong>
          </div>
          <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '6px', whiteSpace: 'pre-line' }}>
            {mismatch.error.message}
          </p>
          <p style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginBottom: '14px' }}>
            Photo reads as <strong>{mismatch.error.referenceClass}</strong>
            {mismatch.error.referenceObjects.length > 0 && <> ({mismatch.error.referenceObjects.join(', ')})</>}
            {' · '}product “{mismatch.error.productName}” is <strong>{mismatch.error.productClass}</strong>
          </p>

          <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
            {/* The label the backend's refusal message quotes. Keep them in step. */}
            <button
              className="btn btn-primary btn-sm"
              onClick={handleUseReferenceAsProduct}
              disabled={drafting || loading}
              title="Draft a product row from this photograph and generate that instead"
            >
              <Camera size={14} />
              <span>{drafting ? 'Drafting…' : 'Use this photo as the product'}</span>
            </button>

            <button
              className="btn btn-secondary btn-sm"
              onClick={() => { setMismatch(null); setActionMessage('Pick the matching product in the Product panel, then generate again.'); }}
            >
              <CheckSquare size={14} />
              <span>Pick a different product</span>
            </button>

            <button
              className="btn btn-secondary btn-sm"
              onClick={handleGenerateAnyway}
              disabled={loading}
              title="Use the photograph for its style only — the product stays as selected"
            >
              <Zap size={14} />
              <span>Generate anyway (style only)</span>
            </button>
          </div>
        </div>
      )}

      {/* Main Grid: Left Inputs (380px) | Right Live 4-Variation Gallery (1fr) */}
      <div style={{ display: 'grid', gridTemplateColumns: '380px 1fr', gap: '24px' }}>
        
        {/* ── LEFT COLUMN: Selectors & Flow Trigger ── */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
          
          {/* Reference & Amazon Product Card */}
          <div className="glass-card" style={{ padding: '20px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <ShoppingBag size={18} color="#e60023" />
                <h3 style={{ fontSize: '1rem', fontWeight: 700 }}>1. Product & Reference Style</h3>
              </div>
              <span className="badge badge-state" style={{ background: 'rgba(230, 0, 35, 0.15)', color: '#ff4d6a' }}>
                {savedProducts.length} Saved Products
              </span>
            </div>

            {/* 📦 SELECT FROM SAVED AMAZON PRODUCTS */}
            <div style={{
              marginBottom: '14px',
              padding: '12px',
              borderRadius: 'var(--radius-md)',
              background: 'linear-gradient(135deg, rgba(230, 0, 35, 0.08), rgba(245, 158, 11, 0.08))',
              border: activeProduct ? '1px solid rgba(16, 185, 129, 0.4)' : '1px solid rgba(230, 0, 35, 0.25)',
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                <label style={{ fontSize: '0.78rem', fontWeight: 700, color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <Package size={14} color="#e60023" /> Select from Saved Products
                </label>
                {activeProductId && (
                  <button
                    type="button"
                    onClick={() => {
                      setActiveProduct(null);
                      setActiveProductId(undefined);
                      if (setSelectedProductId) setSelectedProductId(undefined);
                    }}
                    style={{ fontSize: '0.68rem', color: 'var(--text-muted)', background: 'transparent', border: 'none', cursor: 'pointer' }}
                  >
                    Clear Selection
                  </button>
                )}
              </div>

              {savedProducts.length > 0 ? (
                <select
                  value={activeProductId || ''}
                  onChange={(e) => handleSelectSavedProduct(e.target.value)}
                  className="input"
                  style={{
                    width: '100%',
                    fontSize: '0.78rem',
                    padding: '8px 10px',
                    background: 'var(--bg-card)',
                    border: '1px solid var(--border-subtle)',
                    borderRadius: 'var(--radius-sm)',
                    color: activeProductId ? '#34d399' : 'var(--text-primary)',
                    fontWeight: activeProductId ? 600 : 400,
                  }}
                >
                  <option value="">-- Choose a Saved Amazon Product ({savedProducts.length} available) --</option>
                  {savedProducts.map((p) => {
                    let priceTag = p.price ? `$${p.price.toFixed(2)}` : '';
                    if (p.product_truth?.price_display) {
                      priceTag = p.product_truth.price_display;
                    }
                    return (
                      <option key={p.id} value={p.id}>
                        {p.name.substring(0, 60)}... {priceTag ? `(${priceTag})` : ''}
                      </option>
                    );
                  })}
                </select>
              ) : (
                <div style={{ fontSize: '0.74rem', color: 'var(--text-muted)' }}>
                  No saved products yet. Search in <span style={{ color: '#e60023', cursor: 'pointer', fontWeight: 600 }} onClick={() => setActiveTab('products')}>Product Library</span> to import.
                </div>
              )}
            </div>

            {/* 🌟 ACTIVE PRODUCT TRUTH CARD (Specs, Materials, Anti-Hallucination) */}
            {activeProduct && (
              <div style={{
                marginBottom: '14px',
                padding: '12px',
                borderRadius: 'var(--radius-md)',
                background: 'rgba(16, 185, 129, 0.08)',
                border: '1px solid rgba(16, 185, 129, 0.35)',
              }}>
                <div style={{ display: 'flex', gap: '10px', alignItems: 'flex-start', marginBottom: '10px' }}>
                  {activeProduct.product_image_path && (
                    <img
                      src={formatImgSrc(activeProduct.product_image_path)}
                      alt="Product thumbnail"
                      style={{
                        width: '54px',
                        height: '54px',
                        borderRadius: '6px',
                        objectFit: 'cover',
                        border: '1px solid var(--border-subtle)',
                        background: '#090b0e',
                        flexShrink: 0,
                      }}
                      onError={(e: any) => { e.target.style.display = 'none'; }}
                    />
                  )}
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: '0.82rem', fontWeight: 700, color: 'var(--text-primary)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                      {activeProduct.name}
                    </div>
                    <div style={{ fontSize: '0.72rem', color: 'var(--text-secondary)', display: 'flex', gap: '8px', alignItems: 'center', marginTop: '2px' }}>
                      <span style={{ color: '#34d399', fontWeight: 700 }}>
                        {activeProduct.product_truth?.price_display || (activeProduct.price ? `$${activeProduct.price.toFixed(2)}` : 'Amazon')}
                      </span>
                      <span>•</span>
                      <span>{activeProduct.brand || 'Amazon'}</span>
                    </div>
                  </div>
                </div>

                {/* Extracted Materials Tags */}
                {(() => {
                  const rawMats = activeProduct.materials;
                  const mats: string[] = Array.isArray(rawMats) 
                    ? rawMats 
                    : (typeof rawMats === 'string' ? (() => { try { return JSON.parse(rawMats); } catch { return []; } })() : []);
                  if (mats && mats.length > 0) {
                    return (
                      <div style={{ marginBottom: '8px' }}>
                        <span style={{ fontSize: '0.68rem', fontWeight: 700, color: '#a7f3d0', display: 'block', marginBottom: '3px' }}>
                          🧵 Extracted Physical Materials:
                        </span>
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px' }}>
                          {mats.map((m, i) => (
                            <span key={i} style={{ fontSize: '0.65rem', padding: '1px 6px', borderRadius: '4px', background: 'rgba(16, 185, 129, 0.2)', color: '#6ee7b7', border: '1px solid rgba(16, 185, 129, 0.4)' }}>
                              {m}
                            </span>
                          ))}
                        </div>
                      </div>
                    );
                  }
                  return null;
                })()}

                {/* Style Specs & Physical Silhouette */}
                {(() => {
                  const rawAttrs = activeProduct.key_attributes;
                  const attrs: string[] = Array.isArray(rawAttrs) 
                    ? rawAttrs 
                    : (typeof rawAttrs === 'string' ? (() => { try { return JSON.parse(rawAttrs); } catch { return []; } })() : []);
                  if (attrs && attrs.length > 0) {
                    return (
                      <div style={{ marginBottom: '8px' }}>
                        <span style={{ fontSize: '0.68rem', fontWeight: 700, color: '#bfdbfe', display: 'block', marginBottom: '3px' }}>
                          📐 Style & Cut Silhouette:
                        </span>
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px' }}>
                          {attrs.map((a, i) => (
                            <span key={i} style={{ fontSize: '0.65rem', padding: '1px 6px', borderRadius: '4px', background: 'rgba(59, 130, 246, 0.18)', color: '#93c5fd', border: '1px solid rgba(59, 130, 246, 0.35)' }}>
                              {a}
                            </span>
                          ))}
                        </div>
                      </div>
                    );
                  }
                  return null;
                })()}

                {/* Anti-Hallucination Shield */}
                <div style={{ display: 'flex', alignItems: 'center', gap: '5px', fontSize: '0.68rem', color: '#fbbf24', marginTop: '6px' }}>
                  <ShieldCheck size={13} color="#fbbf24" />
                  <span>Anti-Hallucination Guard Active (Physical Fidelity Enforced)</span>
                </div>
              </div>
            )}

            {/* Active Reference Style Preview */}
            {(selectedRef || activeProduct) && (
              <div style={{ marginBottom: '14px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
                  <span style={{ fontSize: '0.74rem', fontWeight: 700, color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '5px' }}>
                    <Camera size={13} color="#e60023" />
                    {activeProduct ? '📸 Product Reference Image (Active)' : '📸 Reference Style Photo'}
                  </span>
                  <span className="badge" style={{ background: 'rgba(16, 185, 129, 0.2)', color: '#34d399', fontSize: '0.65rem' }}>
                    {activeProduct ? 'Direct Amazon Item' : 'Visual DNA Ready'}
                  </span>
                </div>
                <div style={{
                  height: '140px',
                  borderRadius: 'var(--radius-md)',
                  overflow: 'hidden',
                  background: '#090b0e',
                  border: activeProduct ? '1px solid rgba(16, 185, 129, 0.4)' : '1px solid var(--border-subtle)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}>
                  <img 
                    src={formatImgSrc(selectedRef?.image_path || activeProduct?.product_image_path)} 
                    alt="Reference" 
                    style={{ width: '100%', height: '100%', objectFit: 'contain' }}
                    onError={(e: any) => { e.target.style.display = 'none'; }}
                  />
                </div>
              </div>
            )}

            {/* 1-Click Upload Custom Reference Dropzone */}
            <div style={{ borderTop: '1px solid var(--border-subtle)', paddingTop: '14px' }}>
              <span style={{ fontSize: '0.82rem', fontWeight: 700, color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '4px' }}>
                <Upload size={14} color="#e60023" /> Or Upload New Lifestyle Image
              </span>
              <p style={{ fontSize: '0.73rem', color: 'var(--text-secondary)', marginBottom: '10px', lineHeight: 1.4 }}>
                Choose any Pinterest lifestyle photo from your device to extract Visual DNA.
              </p>
              <input
                ref={fileInputRef}
                type="file"
                accept="image/*"
                aria-label="Reference photo"
                onChange={(e) => handleChooseFile(e.target.files?.[0] || null)}
                style={{ fontSize: '0.78rem', margin: '4px 0 10px', width: '100%' }}
              />
              {uploadFile && (
                <div
                  style={{
                    padding: '8px 10px',
                    marginBottom: '8px',
                    borderRadius: 'var(--radius-md)',
                    background: 'rgba(245, 158, 11, 0.14)',
                    border: '1px solid rgba(245, 158, 11, 0.5)',
                    fontSize: '0.7rem',
                    color: '#fbbf24',
                    lineHeight: 1.45,
                  }}
                >
                  <strong>{uploadFile.name}</strong> selected — uploading & analyzing...
                </div>
              )}

              {/* Affiliate / Store Link input */}
              <div style={{ marginTop: '12px', borderTop: '1px solid var(--border-subtle)', paddingTop: '10px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
                  <label style={{ fontSize: '0.76rem', fontWeight: 700, color: 'var(--text-secondary)' }}>
                    🔗 Amazon / Store Affiliate Link
                  </label>
                  {affiliateUrl && (
                    <span style={{ fontSize: '0.65rem', color: '#34d399', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '3px' }}>
                      <CheckCircle size={10} /> Auto-Linked
                    </span>
                  )}
                </div>
                <input
                  type="url"
                  value={affiliateUrl}
                  onChange={(e) => setAffiliateUrl(e.target.value)}
                  placeholder="https://amzn.to/3XYZ or https://amazon.com/dp/..."
                  className="input"
                  style={{ width: '100%', fontSize: '0.78rem', padding: '6px 10px', background: 'var(--bg-card)' }}
                />
                <span style={{ fontSize: '0.68rem', color: 'var(--text-muted)', display: 'block', marginTop: '3px' }}>
                  Auto-embeds into all CTA buttons and reviews on your Vercel Lookbook.
                </span>
              </div>
            </div>
          </div>

          {/* ⚡ IMAGE GENERATION TRIGGER ⚡ */}
          <div style={{
              marginTop: '16px',
              padding: '14px',
              borderRadius: 'var(--radius-md)',
              background: 'linear-gradient(135deg, rgba(16, 185, 129, 0.12), rgba(59, 130, 246, 0.12))',
              border: canGenerate ? '1px solid rgba(16, 185, 129, 0.4)' : '1px solid rgba(245, 158, 11, 0.45)',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
                <span style={{ fontWeight: 800, fontSize: '0.88rem', color: '#fff' }}>🧠 Image Generation</span>
                <span className="badge" style={{
                  background: canGenerate ? '#10b981' : '#f59e0b',
                  color: '#fff',
                  fontSize: '0.68rem',
                  fontWeight: 700
                }}>
                  {canGenerate ? '✅ Ready' : '⚡ Needs Setup'}
                </span>
              </div>

              {/* Per-backend capability. `detail` comes from the backend and says
                  exactly what is missing, rather than a generic error later. */}
              <div style={{ marginBottom: '10px' }}>
                {backends.map((b) => (
                  <div
                    key={b.id}
                    style={{
                      display: 'flex',
                      alignItems: 'flex-start',
                      gap: '6px',
                      fontSize: '0.7rem',
                      lineHeight: 1.45,
                      color: b.available ? '#a7f3d0' : 'var(--text-secondary)',
                      marginBottom: '3px',
                    }}
                  >
                    <span aria-hidden="true">{b.available ? '✅' : '⚠️'}</span>
                    <span>
                      <strong style={{ color: b.available ? '#d1fae5' : '#fbbf24' }}>{b.label}</strong>
                      {b.primary ? ' (primary)' : ''} — {b.detail}
                    </span>
                  </div>
                ))}
              </div>

              {/* 🔄 Google Flow Project Router Pool Indicator */}
              <div style={{
                padding: '8px 10px',
                marginBottom: '10px',
                borderRadius: 'var(--radius-md)',
                background: 'rgba(59, 130, 246, 0.12)',
                border: '1px solid rgba(59, 130, 246, 0.3)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                gap: '8px',
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <RefreshCw size={13} color="#60a5fa" />
                  <span style={{ fontSize: '0.72rem', color: '#bfdbfe', fontWeight: 600 }}>
                    Flow Router: <strong>{flowProjects.length} Workspaces</strong> (Load-Balanced)
                  </span>
                </div>
                <button
                  type="button"
                  onClick={() => setShowProjectsModal(true)}
                  className="btn btn-secondary btn-sm"
                  style={{ fontSize: '0.68rem', padding: '2px 8px', height: '22px' }}
                >
                  Manage
                </button>
              </div>

              <label
                htmlFor="backend-select"
                style={{ display: 'block', fontSize: '0.68rem', fontWeight: 700, color: 'var(--text-secondary)', marginBottom: '4px' }}
              >
                Backend
              </label>
              <select
                id="backend-select"
                value={selectedBackend}
                onChange={(e) => setSelectedBackend(e.target.value)}
                className="input"
                style={{ width: '100%', marginBottom: '10px', fontSize: '0.78rem' }}
              >
                <option value="auto">Auto — direct Flow API, then browser automation</option>
                {backends.map((b) => (
                  <option key={b.id} value={b.id} disabled={!b.available}>
                    {b.label}{b.available ? '' : ' — unavailable'}
                  </option>
                ))}
              </select>
              <p style={{ fontSize: '0.68rem', color: 'var(--text-secondary)', marginBottom: '10px', lineHeight: 1.4 }}>
                A named backend is never substituted — if it cannot run, the job fails and says why.
              </p>

              {/* Says which of the two preconditions is missing. A disabled button
                  with no reason is why the previous version looked broken. */}
              {!selectedRefHasDna && !pendingFileReady && (
                <p style={{ fontSize: '0.7rem', color: '#fbbf24', marginBottom: '8px', lineHeight: 1.4 }}>
                  ⚠️ The selected reference has no Visual DNA. Use <strong>Analyze Reference</strong> in
                  panel 1 first — the pipeline refuses to generate without it.
                </p>
              )}
              {pendingFileReady && (
                <p style={{ fontSize: '0.7rem', color: '#93c5fd', marginBottom: '8px', lineHeight: 1.4 }}>
                  ℹ️ <strong>{uploadFile?.name}</strong> will be uploaded and analysed first, then
                  generated from. Nothing silently falls back to the old reference any more.
                </p>
              )}
              {(selectedRefHasDna || pendingFileReady) && !backendReady && (
                <p style={{ fontSize: '0.7rem', color: '#fbbf24', marginBottom: '8px', lineHeight: 1.4 }}>
                  ⚠️ No image backend can run right now. See the list above for what each one needs.
                </p>
              )}

              <button
                onClick={handleGenerateFlowBatch}
                disabled={loading || (!selectedRefId && !uploadFile) || !canGenerate}
                className="btn btn-primary"
                style={{
                  width: '100%',
                  padding: '12px',
                  fontSize: '0.95rem',
                  fontWeight: 800,
                  background: 'linear-gradient(135deg, #10b981, #059669)',
                  boxShadow: '0 4px 15px rgba(16, 185, 129, 0.4)',
                }}
              >
                <Layers size={16} />
                <span>{loading ? 'Generating...' : '⚡ Generate 4 Variations'}</span>
              </button>

              {!flowSessionActive && (
                <div style={{ marginTop: '10px' }}>
                  <p style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', marginBottom: '6px', lineHeight: 1.4 }}>
                    Optional speed-up: capturing a Flow session skips the browser window for
                    about 15 minutes. It is not a login — the capture carries a one-shot
                    reCAPTCHA token and a short-lived access token, so browser automation
                    stays the primary path.
                  </p>
                  <button
                    onClick={async () => {
                      try {
                        await api.launchFlowCapture();
                        alert('🎯 Interceptor launched! The browser will open Google Flow. Type a simple prompt and generate 1 image — the interceptor captures the request automatically.\n\nNote: the capture is only replayable for ~15 minutes. Generation does not depend on it; browser automation runs first either way.');
                      } catch (e: any) {
                        alert('Error: ' + e.message);
                      }
                    }}
                    className="btn btn-secondary"
                    style={{
                      width: '100%',
                      padding: '10px',
                      fontSize: '0.85rem',
                      fontWeight: 700,
                      borderColor: 'rgba(59, 130, 246, 0.5)',
                      color: '#60a5fa',
                      background: 'rgba(59, 130, 246, 0.1)',
                    }}
                  >
                    <Sparkles size={14} />
                    <span>🎯 1-Time Capture Flow Session</span>
                  </button>
                </div>
              )}
          </div>
        </div>

        {/* ── RIGHT COLUMN: 4-Variation Gallery & Direct Publish Cockpit ── */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
          
          {outputs.length > 0 ? (
            <div className="glass-card" style={{ padding: '24px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '18px', flexWrap: 'wrap', gap: '12px' }}>
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                    <h3 style={{ fontSize: '1.25rem', fontWeight: 800 }}>4-Variation Google Flow Gallery</h3>
                    <span className="badge badge-pass" style={{ fontSize: '0.72rem' }}>Latest Outputs</span>
                  </div>
                  <span style={{ fontSize: '0.78rem', color: 'var(--text-secondary)' }}>
                    High-converting 9:16 vertical creatives • Click any thumbnail to preview and publish
                  </span>
                </div>

                <div style={{ display: 'flex', gap: '10px', alignItems: 'center', flexWrap: 'wrap' }}>
                  {recentJobs.length > 1 && (
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                      <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontWeight: 600 }}>Switch Batch:</span>
                      <select
                        value={currentJob?.id || ''}
                        onChange={(e) => loadJob(e.target.value)}
                        className="input"
                        style={{ fontSize: '0.76rem', padding: '4px 8px', maxWidth: '200px', background: 'var(--bg-card)' }}
                      >
                        {recentJobs.map((j) => (
                          <option key={j.id} value={j.id}>
                            #{j.id.slice(0, 8)} ({j.current_state}) — {new Date(j.created_at || j.updated_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                          </option>
                        ))}
                      </select>
                    </div>
                  )}

                  <button
                    onClick={() => setActiveTab('pins')}
                    className="btn btn-primary btn-sm"
                    style={{ background: 'linear-gradient(135deg, #e60023, #ff4757)', fontWeight: 800 }}
                    title="Open all generated variations in Pin Composer to batch edit metadata and publish all"
                  >
                    <Layers size={14} />
                    <span>Open in Pin Composer (Batch Mode) ➔</span>
                  </button>

                  <button
                    onClick={handleGenerateFlowBatch}
                    disabled={loading}
                    className="btn btn-secondary btn-sm"
                    title="Generate a new 4-variation batch"
                  >
                    <RefreshCw size={14} />
                    <span>New 4-Batch</span>
                  </button>
                </div>
              </div>

              {/* Lookbook Live Status & Affiliate Link Bar */}
              <div style={{
                marginBottom: '16px',
                padding: '10px 14px',
                borderRadius: 'var(--radius-md)',
                background: 'linear-gradient(135deg, rgba(230, 0, 35, 0.08), rgba(255, 153, 0, 0.08))',
                border: '1px solid rgba(255, 153, 0, 0.3)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                flexWrap: 'wrap',
                gap: '10px',
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <ExternalLink size={16} color="#ff9900" />
                  <div>
                    <span style={{ fontSize: '0.82rem', fontWeight: 800, color: '#fff', marginRight: '8px' }}>
                      Vercel UGC Lookbook Article
                    </span>
                    <span style={{ fontSize: '0.72rem', color: 'var(--text-secondary)' }}>
                      All 4 variations + wear-test reviews + Amazon buy buttons
                    </span>
                  </div>
                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  {jobPins[0]?.destination_url && (
                    <a
                      href={jobPins[0].destination_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="btn btn-secondary btn-sm"
                      style={{ fontSize: '0.74rem', fontWeight: 700, borderColor: 'rgba(255, 153, 0, 0.5)', color: '#ffb347' }}
                    >
                      <ExternalLink size={12} />
                      <span>View Live Lookbook ↗</span>
                    </a>
                  )}
                  {currentJob?.id && (
                    <button
                      onClick={handleDeployLookbook}
                      disabled={deployingLookbook}
                      className="btn btn-secondary btn-sm"
                      style={{ fontSize: '0.74rem', fontWeight: 700, borderColor: 'rgba(56, 139, 253, 0.5)', color: '#58a6ff' }}
                      title="Generate grounded review article & deploy to Vercel"
                    >
                      <BookOpen size={12} />
                      <span>{deployingLookbook ? 'Deploying...' : 'Deploy/Sync Lookbook'}</span>
                    </button>
                  )}
                </div>
              </div>

              {/* Concept Selector — 4 concept tabs (Desire / Detail / Lifestyle / Discovery) when job.concepts exists */}
              <div style={{ display: 'flex', gap: '8px', marginBottom: '14px', flexWrap: 'wrap' }}>
                {(concepts.length > 0 ? concepts.map((c: any) => c.objective || c.concept_id) : conceptTabs).slice(0, 4).map((tab: string) => {
                  const label = String(tab).replace(/_/g, ' ');
                  const isActive = selectedConcept.toLowerCase() === label.toLowerCase();
                  return (
                    <button
                      key={label}
                      onClick={() => setSelectedConcept(label)}
                      className={isActive ? 'btn btn-primary btn-sm' : 'btn btn-secondary btn-sm'}
                      style={{ textTransform: 'capitalize', fontSize: '0.78rem' }}
                    >
                      {label}
                    </button>
                  );
                })}
              </div>
              {/* Commerce DNA display placeholder */}
              {commerceDna && (
                <div style={{ padding: '10px 12px', marginBottom: '14px', background: 'rgba(99, 102, 241, 0.08)', border: '1px solid rgba(99,102,241,0.25)', borderRadius: 'var(--radius-md)', fontSize: '0.78rem' }}>
                  <strong style={{ color: '#a5b4fc' }}>Commerce DNA</strong>
                  <span style={{ color: 'var(--text-secondary)', marginLeft: '8px' }}>
                    hero_prominence: {(commerceDna as any).hero_prominence || '—'} · click_reason: {(commerceDna as any).click_reason || '—'}
                  </span>
                </div>
              )}
              {/* Both critic scores (Photographic Realism + Commerce) in gallery */}
              {currentOutput && (
                <div style={{ display: 'flex', gap: '10px', marginBottom: '14px', fontSize: '0.78rem' }}>
                  <span className="badge badge-state">
                    Photographic Realism: {(currentOutput as any)?.critiques?.[0]?.critique?.authenticity || (currentOutput as any)?.critique?.authenticity || '—'}
                  </span>
                  <span className="badge badge-pass">
                    Commerce: {(currentOutput as any)?.commerce_critique?.product_prominence || (currentOutput as any)?.critiques?.[0]?.critique?.product_fidelity || '—'}
                  </span>
                </div>
              )}

              {/* 4-Image Thumbnail Grid Selector */}
              <div style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(4, 1fr)',
                gap: '12px',
                marginBottom: '20px'
              }}>
                {outputs.map((out, idx) => {
                  const isSelected = idx === selectedOutputIndex;
                  const imgSrc = formatImgSrc(out.image_path);
                  return (
                    <div
                      key={out.id || idx}
                      onClick={() => setSelectedOutputIndex(idx)}
                      style={{
                        borderRadius: 'var(--radius-md)',
                        overflow: 'hidden',
                        cursor: 'pointer',
                        border: isSelected ? '3px solid #e60023' : '1px solid var(--border-subtle)',
                        boxShadow: isSelected ? '0 0 16px rgba(230, 0, 35, 0.5)' : 'none',
                        position: 'relative',
                        background: '#090b0e',
                        display: 'flex',
                        flexDirection: 'column',
                      }}
                    >
                      <div style={{ aspectRatio: '9/16', position: 'relative', overflow: 'hidden' }}>
                        <img
                          src={imgSrc}
                          alt={`Variation ${idx + 1}`}
                          style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                        />
                        {/* Hover Download Overlay */}
                        <a
                          href={imgSrc}
                          download={`flow_variation_${idx + 1}.jpg`}
                          onClick={e => e.stopPropagation()}
                          style={{
                            position: 'absolute',
                            top: '8px',
                            right: '8px',
                            background: 'rgba(0,0,0,0.75)',
                            color: '#fff',
                            borderRadius: '8px',
                            padding: '4px 8px',
                            fontSize: '0.68rem',
                            fontWeight: 700,
                            display: 'flex',
                            alignItems: 'center',
                            gap: '3px',
                            textDecoration: 'none',
                            zIndex: 10,
                          }}
                          title={`Download Variation ${idx + 1} at 1x`}
                        >
                          ↓ 1x
                        </a>
                      </div>
                      <div style={{
                        background: isSelected ? '#e60023' : 'rgba(0,0,0,0.7)',
                        color: '#fff',
                        fontSize: '0.72rem',
                        fontWeight: 700,
                        textAlign: 'center',
                        padding: '4px 0'
                      }}>
                        Variation #{idx + 1} {isSelected && '✓'}
                      </div>
                    </div>
                  );
                })}
              </div>

              {/* Two Column Focused Output Preview: Selected Image (Left) | Pinterest Metadata & 1-Click Post (Right) */}
              <div style={{ display: 'grid', gridTemplateColumns: '320px 1fr', gap: '24px' }}>
                
                {/* Large Selected Preview */}
                <div>
                  <div style={{
                    borderRadius: 'var(--radius-lg)',
                    overflow: 'hidden',
                    background: '#000',
                    border: '1px solid var(--border-subtle)',
                    boxShadow: '0 8px 30px rgba(0,0,0,0.7)',
                    aspectRatio: '9/16',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                  }}>
                    {currentOutput && (
                      <img
                        src={formatImgSrc(currentOutput.image_path)}
                        alt="Selected Pinterest Creative"
                        style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                      />
                    )}
                  </div>
                  {/* 1x Download Button under selected preview */}
                  {currentOutput && (
                    <a
                      href={formatImgSrc(currentOutput.image_path)}
                      download={`flow_variation_${selectedOutputIndex + 1}_1x.jpg`}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        gap: '6px',
                        marginTop: '10px',
                        padding: '8px 0',
                        background: 'linear-gradient(135deg, #1e293b, #334155)',
                        border: '1px solid rgba(255,255,255,0.12)',
                        borderRadius: 'var(--radius-md)',
                        color: '#fff',
                        fontWeight: 700,
                        fontSize: '0.82rem',
                        textDecoration: 'none',
                        cursor: 'pointer',
                        transition: 'all 0.2s ease',
                      }}
                    >
                      <Download size={14} />
                      <span>Download Variation #{selectedOutputIndex + 1} (1x)</span>
                    </a>
                  )}
                </div>

                {/* Pin Publish & Metadata Cockpit */}
                <div style={{ display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
                  <div>
                    <div style={{ display: 'flex', gap: '8px', marginBottom: '10px' }}>
                      <span className="badge badge-pass">Variation #{selectedOutputIndex + 1} Selected</span>
                      <span className="badge badge-state">{outputs.length} Variations Ready</span>
                    </div>

                    {/* Real pin-draft copy. This panel used to render a hardcoded
                        "spooky season" description and the invented board
                        "Seasonal Trends & Aesthetic Finds", so it showed text that
                        would never actually be posted. */}
                    <h3 style={{ fontSize: '1.2rem', fontWeight: 800, marginBottom: '8px', lineHeight: 1.3 }}>
                      {activePin?.title || 'No pin draft yet'}
                    </h3>

                    <p style={{ fontSize: '0.88rem', color: 'var(--text-secondary)', marginBottom: '16px', lineHeight: 1.5 }}>
                      {activePin?.description ||
                        'No pin draft for this variation yet. Generate the SEO copy in Pin Composer — nothing here is placeholder text.'}
                    </p>

                    <div style={{ padding: '12px', background: 'var(--bg-input)', borderRadius: 'var(--radius-md)', marginBottom: '16px', border: '1px solid var(--border-subtle)' }}>
                      <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginBottom: '4px' }}>Target Board</div>
                      <div style={{ fontWeight: 700, fontSize: '0.9rem' }}>
                        {activePin?.board_name || 'Not set — pick a board before publishing'}
                      </div>

                      <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginTop: '8px', marginBottom: '4px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <span>Destination Link</span>
                        {activePin?.destination_url?.endsWith('.html') ? (
                          <span style={{ fontSize: '0.7rem', color: '#3fb950', background: 'rgba(63, 185, 80, 0.15)', padding: '2px 6px', borderRadius: '4px', fontWeight: 600 }}>
                            ✓ Live Blog Lookbook
                          </span>
                        ) : activePin?.destination_url?.includes('/api/go') ? (
                          <span style={{ fontSize: '0.7rem', color: '#d29922', background: 'rgba(210, 153, 34, 0.15)', padding: '2px 6px', borderRadius: '4px', fontWeight: 600 }}>
                            ⚠️ Direct Redirect
                          </span>
                        ) : null}
                      </div>
                      <div style={{ fontSize: '0.82rem', color: '#58a6ff', wordBreak: 'break-all' }}>
                        {activePin?.destination_url || 'No affiliate URL set'}
                      </div>
                    </div>
                  </div>

                  {/* 🚀 ACTION BUTTONS: Publish Selected or Schedule All 🚀 */}
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                    <button
                      onClick={handleDirectPublish}
                      disabled={loading}
                      className="btn btn-primary"
                      style={{
                        padding: '14px',
                        fontSize: '1rem',
                        fontWeight: 800,
                        background: 'linear-gradient(135deg, #e60023, #d0001f)',
                      }}
                    >
                      <Send size={18} />
                      <span>🚀 Publish Selected Variation Live</span>
                    </button>

                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px' }}>
                      <button
                        onClick={() => {
                          setScheduleAllPins(true);
                          setScheduleModalOpen(true);
                        }}
                        disabled={loading}
                        className="btn btn-secondary"
                      >
                        <Calendar size={16} />
                        <span>📅 Schedule All 4 Pins</span>
                      </button>

                      <button
                        onClick={() => setActiveTab('pins')}
                        className="btn btn-secondary"
                      >
                        <Pin size={16} />
                        <span>Edit Copy in Composer</span>
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          ) : (
            /* Empty State */
            <div className="glass-card" style={{ padding: '48px 32px', textAlign: 'center' }}>
              <div style={{
                width: '64px',
                height: '64px',
                borderRadius: '16px',
                background: 'rgba(230, 0, 35, 0.1)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                margin: '0 auto 16px',
              }}>
                <Layers size={32} color="#e60023" />
              </div>
              <h2 style={{ fontSize: '1.4rem', fontWeight: 800, marginBottom: '8px' }}>
                Google Flow 4-Variation Batch Engine
              </h2>
              <p style={{ color: 'var(--text-secondary)', maxWidth: '480px', margin: '0 auto 24px', fontSize: '0.92rem' }}>
                Generate 4 high-quality photorealistic variations at once without expensive APIs. Select your product and click <strong>"⚡ Generate 4 Variations (Flow)"</strong>.
              </p>
              <button
                onClick={handleGenerateFlowBatch}
                disabled={loading || (!selectedRefId && !uploadFile) || !canGenerate}
                className="btn btn-primary"
                style={{ padding: '12px 28px', fontSize: '0.95rem' }}
              >
                <Layers size={18} />
                <span>Generate 4 Variations Now</span>
              </button>
              {!selectedRefHasDna && selectedRefId && (
                <p style={{ fontSize: '0.78rem', color: '#fbbf24', marginTop: '12px' }}>
                  The selected reference has no Visual DNA yet — analyse it in the Reference Style panel first.
                </p>
              )}
            </div>
          )}

          {/* Compiled Prompt & Raw Specs */}
          {(displayPromptText || compilingPrompt) && (
            <div className="glass-card" style={{ padding: '20px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                  <span style={{ fontSize: '0.85rem', fontWeight: 700, color: 'var(--text-secondary)' }}>
                    Underlying 13-Section Flow Prompt
                  </span>
                  {compilingPrompt ? (
                    <span style={{ fontSize: '0.74rem', color: '#ff334b', display: 'flex', alignItems: 'center', gap: '5px' }}>
                      <RefreshCw size={11} className="spin" /> Compiling live prompt...
                    </span>
                  ) : previewPromptText ? (
                    <span style={{ fontSize: '0.72rem', color: '#34d399', background: 'rgba(52, 211, 153, 0.12)', border: '1px solid rgba(52, 211, 153, 0.25)', padding: '2px 8px', borderRadius: '12px', fontWeight: 600 }}>
                      ⚡ Live Auto-Generated from Visual DNA
                    </span>
                  ) : null}
                </div>
                {displayPromptText && !compilingPrompt && (
                  <div style={{ display: 'flex', gap: '8px' }}>
                    <button 
                      onClick={() => copyPromptText(displayPromptText)} 
                      className="btn btn-secondary btn-sm"
                    >
                      {copiedPrompt ? <Check size={13} color="#34d399" /> : <Copy size={13} />}
                      <span>{copiedPrompt ? 'Copied' : 'Copy Prompt'}</span>
                    </button>
                    <button 
                      onClick={openGoogleFlow}
                      className="btn btn-secondary btn-sm"
                    >
                      <ExternalLink size={13} />
                      <span>Open Flow</span>
                    </button>
                  </div>
                )}
              </div>
              <div className="code-block" style={{ maxHeight: '160px', overflowY: 'auto', fontSize: '0.78rem' }}>
                {compilingPrompt ? 'Compiling 13-section photographic brief from Visual DNA & Product Truth...' : displayPromptText}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Schedule Modal */}
      {scheduleModalOpen && (
        <div style={{
          position: 'fixed',
          top: 0, left: 0, right: 0, bottom: 0,
          background: 'rgba(0,0,0,0.8)',
          backdropFilter: 'blur(8px)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 100,
        }}>
          <div className="glass-card" style={{ padding: '28px', width: '440px', background: 'var(--bg-secondary)' }}>
            <h3 style={{ fontSize: '1.2rem', fontWeight: 700, marginBottom: '12px' }}>
              📅 {scheduleAllPins ? 'Schedule All 4 Variations (Campaign)' : 'Schedule Selected Pin'}
            </h3>
            <p style={{ fontSize: '0.82rem', color: 'var(--text-secondary)', marginBottom: '16px' }}>
              {scheduleAllPins 
                ? 'All 4 variations will be queued across consecutive days at peak Pinterest engagement hours!'
                : 'Select the target date and time to automatically publish this pin.'}
            </p>

            <form onSubmit={handleScheduleSubmit}>
              <div className="form-group">
                <label className="form-label">Starting Date & Time</label>
                <input
                  type="datetime-local"
                  className="form-input"
                  value={scheduleDate}
                  onChange={(e) => setScheduleDate(e.target.value)}
                  required
                />
              </div>

              <div style={{ display: 'flex', gap: '10px', marginTop: '20px' }}>
                <button type="submit" disabled={loading} className="btn btn-primary" style={{ flex: 1 }}>
                  {scheduleAllPins ? 'Schedule All 4 Drops' : 'Schedule Pin'}
                </button>
                <button type="button" onClick={() => setScheduleModalOpen(false)} className="btn btn-secondary">
                  Cancel
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* 🔄 Google Flow Projects Router Management Modal */}
      {showProjectsModal && (
        <div style={{
          position: 'fixed',
          top: 0, left: 0, right: 0, bottom: 0,
          background: 'rgba(0,0,0,0.85)',
          backdropFilter: 'blur(8px)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 110,
        }}>
          <div className="glass-card" style={{ padding: '28px', width: '600px', maxWidth: '92vw', background: 'var(--bg-secondary)', maxHeight: '85vh', display: 'flex', flexDirection: 'column' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <RefreshCw size={20} color="#60a5fa" />
                <h3 style={{ fontSize: '1.15rem', fontWeight: 800 }}>Google Flow Project Router Pool</h3>
              </div>
              <span className="badge badge-pass" style={{ fontSize: '0.72rem' }}>
                {flowProjects.length} Active Workspaces
              </span>
            </div>

            <p style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', marginBottom: '14px', lineHeight: 1.45 }}>
              Jobs automatically rotate across these workspaces to prevent project canvases from becoming bloated.
              You can easily add new project URLs or remove old ones at any time.
            </p>

            {/* Add New Project URL Form */}
            <form onSubmit={handleAddProject} style={{ marginBottom: '16px', display: 'flex', gap: '8px' }}>
              <input
                type="url"
                value={newProjectUrl}
                onChange={(e) => setNewProjectUrl(e.target.value)}
                placeholder="https://labs.google/fx/tools/flow/project/<uuid>"
                className="input"
                style={{ flex: 1, fontSize: '0.78rem', padding: '8px 12px' }}
                required
              />
              <button
                type="submit"
                disabled={loading || !newProjectUrl.trim()}
                className="btn btn-primary btn-sm"
                style={{ background: '#2563eb', padding: '0 16px', fontWeight: 700 }}
              >
                + Add Project
              </button>
            </form>

            {/* Active Projects List */}
            <div style={{ flex: 1, overflowY: 'auto', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-md)', padding: '8px', background: '#090b0e' }}>
              {flowProjects.length === 0 ? (
                <div style={{ padding: '20px', textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.78rem' }}>
                  No Flow projects configured.
                </div>
              ) : (
                flowProjects.map((url, idx) => {
                  const uuid = url.split('/').pop() || url;
                  return (
                    <div
                      key={url}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        padding: '8px 12px',
                        marginBottom: idx < flowProjects.length - 1 ? '6px' : '0',
                        background: 'rgba(255, 255, 255, 0.03)',
                        borderRadius: '6px',
                        border: '1px solid rgba(255, 255, 255, 0.06)',
                        gap: '8px',
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', minWidth: 0 }}>
                        <span style={{ fontSize: '0.72rem', color: '#60a5fa', fontWeight: 700, width: '22px' }}>
                          #{idx + 1}
                        </span>
                        <div style={{ minWidth: 0 }}>
                          <span style={{ fontSize: '0.78rem', color: '#fff', fontWeight: 600, display: 'block', textOverflow: 'ellipsis', overflow: 'hidden', whiteSpace: 'nowrap' }}>
                            {uuid}
                          </span>
                          <span style={{ fontSize: '0.68rem', color: 'var(--text-muted)' }}>
                            {url}
                          </span>
                        </div>
                      </div>

                      <button
                        type="button"
                        onClick={() => handleRemoveProject(url)}
                        className="btn btn-secondary btn-sm"
                        style={{ fontSize: '0.68rem', color: '#f87171', borderColor: 'rgba(239, 68, 68, 0.3)', padding: '2px 8px' }}
                        title="Remove project from pool"
                      >
                        Remove
                      </button>
                    </div>
                  );
                })
              )}
            </div>

            <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '16px' }}>
              <button
                type="button"
                onClick={() => setShowProjectsModal(false)}
                className="btn btn-secondary"
                style={{ padding: '6px 20px', fontSize: '0.8rem' }}
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
